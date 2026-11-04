"""Adapters between the academic models and the pure domain rules.

Implements: D47 – keeps ``cross_course`` free of Django.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.audit import audited_delete, audited_save
from apps.core.parameters import SEMESTER_WEEKS, get_parameter

from .cross_course import (
    CrossCourseWarning,
    GroupError,
    SubjectFacts,
    check_group,
    compare_members,
    effective_members,
)
from .enrollment import EffectiveStudents, effective_students
from .messages import GROUP_ERROR_TEXT
from .models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Course,
    CrossCourseSubject,
    CrossCourseSubjectCourse,
    CrossCourseSubjectMember,
    Enrollment,
    StudyPlan,
    Subject,
    SubjectClassLoad,
    Track,
)
from .plans import PlanFacts, plan_in_force
from .preparation import preparation_hours


def facts_for(subject: Subject) -> SubjectFacts:
    """Build the domain facts of a subject.

    Args:
        subject: a saved subject.

    Returns:
        The subject's facts, with weekly hours keyed by class type code.
    """
    weekly: dict[str, Decimal] = {
        load.class_type.code: Decimal(load.weekly_hours)
        for load in subject.class_loads.select_related("class_type")
    }
    return SubjectFacts(
        id=subject.pk,
        course_id=subject.study_plan.course_id,
        plan_id=subject.study_plan_id,
        name=subject.name,
        ects=subject.ects,
        semester=subject.semester,
        curricular_year=subject.curricular_year,
        semester_hours=subject.semester_hours,
        weekly_hours=weekly,
    )


def effective_group_members(group: CrossCourseSubject, academic_year: int) -> list[SubjectFacts]:
    """Return the facts of the group's members that count in an academic year (D48).

    Args:
        group: a saved cross-course group.
        academic_year: start year of the academic year, e.g. 2027.

    Returns:
        The members whose study plan is in force for their curricular year.
    """
    members = [facts_for(m.subject) for m in group.members.select_related("subject__study_plan")]
    plans_by_course: dict[int, list[PlanFacts]] = {}
    for plan in StudyPlan.objects.filter(
        course_id__in={m.course_id for m in members}
    ).select_related("academic_year"):
        plans_by_course.setdefault(plan.course_id, []).append(
            PlanFacts(id=plan.pk, start_year=plan.academic_year.start_year)
        )
    return effective_members(members, plans_by_course, academic_year)


def create_class_group(
    course: Course,
    intake_year: AcademicYear,
    label: str = "",
    last_year: AcademicYear | None = None,
    *,
    track: Track | None = None,
    actor,
    reason: str = "",
) -> ClassGroup:
    """Create a turma with the plan in force for the first year of its intake (D48, D49).

    The creation is written through ``audited_save`` (D54).

    Args:
        course: course of the turma.
        intake_year: academic year in which the turma enters.
        label: letter to tell turmas of the same year apart; empty for the default turma.
        last_year: last academic year, if the turma already ended.
        track: track of the turma, for the years in which the course splits (D79); it must be
            a track of the plan in force for this intake.
        actor: the user creating the turma.
        reason: optional reason (D40).

    Returns:
        The saved turma.

    Raises:
        ValidationError: if no plan of the course has reached the first year at the intake,
            if the track is not a track of that plan, or if the turma itself is invalid (for
            example its last year precedes the intake).
    """
    plans = [
        PlanFacts(id=p.pk, start_year=p.academic_year.start_year)
        for p in StudyPlan.objects.filter(course=course).select_related("academic_year")
    ]
    plan_id = plan_in_force(plans, 1, intake_year.start_year)
    if plan_id is None:
        raise ValidationError(_("Nenhum plano de estudos está em vigor para esta entrada."))
    if track is not None and track.study_plan_id != plan_id:
        raise ValidationError(_("Este percurso não existe no plano em vigor para esta entrada."))
    group = ClassGroup(
        course=course,
        intake_year=intake_year,
        label=label,
        study_plan=StudyPlan.objects.get(pk=plan_id),
        last_academic_year=last_year,
        track=track,
    )
    audited_save(group, actor, reason)
    return group


def subjects_for(group: ClassGroup):
    """Return the subjects of the turma's plan that are taught to it (D79).

    A turma sees the common subjects (no track) and those of its own track; a turma without
    track sees the common ones only. The rule is ``class_groups.subject_applies``.

    Args:
        group: the turma.

    Returns:
        A queryset of the plan's subjects.
    """
    visible = Q(track__isnull=True)
    if group.track_id:
        visible |= Q(track_id=group.track_id)
    return Subject.objects.filter(visible, study_plan_id=group.study_plan_id)


def _plain(value: Decimal) -> str:
    """Format a decimal without trailing zeros, e.g. ``75.00`` as ``75``."""
    return format(value.normalize(), "f")


def check_semester_load(subject: Subject, loads: Mapping[int, Decimal | None]) -> None:
    """Check that the subject has weekly hours and that its semester load matches them (D60).

    Every subject has a weekly load, and the semester load is the weekly load times the number
    of weeks in a semester (a parameter, 15 by default).

    Args:
        subject: the subject, new or existing, with the semester hours to be saved.
        loads: weekly hours being saved, keyed by class type id; ``None`` or zero removes a
            class type. Class types not mentioned keep the hours already stored.

    Raises:
        ValidationError: if the subject would have no weekly hours, or if its semester hours
            differ from the weekly total times the weeks.
    """
    current: dict[int, Decimal] = (
        {}
        if subject.pk is None
        else {load.class_type_id: load.weekly_hours for load in subject.class_loads.all()}
    )
    for class_type_id, hours in loads.items():
        if hours is None or hours == 0:
            current.pop(class_type_id, None)
        else:
            current[class_type_id] = hours
    weekly = sum(current.values(), Decimal("0"))
    if weekly <= 0:
        raise ValidationError(
            str(_("Toda a disciplina tem carga semanal: indique as horas por tipo de aula."))
        )
    weeks = get_parameter(SEMESTER_WEEKS)
    expected = weekly * weeks
    if subject.semester_hours != expected:
        message = str(
            _(
                "A carga semestral (%(actual)s h) tem de ser igual à carga semanal "
                "(%(weekly)s h) × %(weeks)s semanas = %(expected)s h."
            )
        ) % {
            "actual": _plain(subject.semester_hours),
            "weekly": _plain(weekly),
            "weeks": _plain(weeks),
            "expected": _plain(expected),
        }
        raise ValidationError({"semester_hours": [message]})


def save_subject_with_loads(
    subject: Subject,
    loads: Mapping[int, Decimal | None],
    actor,
    reason: str,
    *,
    save_subject: bool,
) -> None:
    """Save a subject and its weekly hours per class type in one audited transaction (D53).

    Each row written (the subject, and every weekly load created, changed or removed) gets
    its own audit entry sharing the same reason. A blank or zero value removes the row of
    that class type. Rows that do not change write nothing.

    Args:
        subject: the subject, new or existing.
        loads: weekly hours keyed by class type id; ``None`` or zero means no hours.
        actor: the user making the change.
        reason: why; required when the subject already exists (D40).
        save_subject: whether the subject's own fields changed and must be saved.

    Raises:
        ValidationError: if a row is refused (for example a missing reason on an update, or
            a new load of an inactive class type), if the subject has no weekly hours or if its
            semester hours differ from the weekly hours times the weeks (D60). Nothing is saved
            in that case.
    """
    check_semester_load(subject, loads)
    with transaction.atomic():
        if save_subject:
            audited_save(subject, actor, reason)
        existing = {
            load.class_type_id: load for load in subject.class_loads.select_related("class_type")
        }
        for class_type_id, hours in loads.items():
            row = existing.get(class_type_id)
            if hours is None or hours == 0:
                if row is not None:
                    audited_delete(row, actor, reason)
            elif row is None:
                class_type = ClassType.objects.get(pk=class_type_id)
                load = SubjectClassLoad(subject=subject, class_type=class_type, weekly_hours=hours)
                audited_save(load, actor, reason)
            elif row.weekly_hours != hours:
                row.weekly_hours = hours
                audited_save(row, actor, reason)


def evaluate_selection(
    subjects: Iterable[Subject], courses: Collection[Course]
) -> tuple[list[GroupError], list[CrossCourseWarning]]:
    """Check a proposed group and compare its members (D47).

    Args:
        subjects: the subjects proposed as members.
        courses: the courses in which the subject would be cross-course.

    Returns:
        The blocking errors and the non-blocking warnings.
    """
    members = [facts_for(s) for s in subjects]
    errors = check_group(members, {c.pk for c in courses})
    return errors, compare_members(members)


def save_cross_course_group(
    group: CrossCourseSubject,
    subjects: Collection[Subject],
    courses: Collection[Course],
    actor,
    reason: str,
    *,
    save_group: bool,
) -> None:
    """Save a group with its members and allowed courses in one audited transaction (D55).

    The group is validated first with ``check_group``. Each row created or removed (the group
    itself, members, allowed courses) gets its own audit entry sharing the same reason.

    Args:
        group: the group, new or existing.
        subjects: the subjects that must be members afterwards.
        courses: the courses in which the group is cross-course afterwards.
        actor: the user making the change.
        reason: why; required when the group already exists (D40).
        save_group: whether the group's own fields (name, notes) must be saved.

    Raises:
        ValidationError: if the group is invalid or a row is refused. Nothing is saved.
    """
    errors = check_group([facts_for(s) for s in subjects], {c.pk for c in courses})
    if errors:
        raise ValidationError([str(GROUP_ERROR_TEXT[e]) for e in errors])
    with transaction.atomic():
        if save_group or group._state.adding:
            audited_save(group, actor, reason)
        members = {m.subject_id: m for m in group.members.all()}
        allowed = {c.course_id: c for c in group.allowed_courses.all()}
        wanted_subjects = {s.pk: s for s in subjects}
        wanted_courses = {c.pk: c for c in courses}
        for subject_id, row in members.items():
            if subject_id not in wanted_subjects:
                audited_delete(row, actor, reason)
        for course_id, row in allowed.items():
            if course_id not in wanted_courses:
                audited_delete(row, actor, reason)
        for subject_id, subject in wanted_subjects.items():
            if subject_id not in members:
                audited_save(
                    CrossCourseSubjectMember(cross_course_subject=group, subject=subject),
                    actor,
                    reason,
                )
        for course_id, course in wanted_courses.items():
            if course_id not in allowed:
                audited_save(
                    CrossCourseSubjectCourse(cross_course_subject=group, course=course),
                    actor,
                    reason,
                )


def delete_cross_course_group(group: CrossCourseSubject, actor, reason: str) -> None:
    """Delete a group after deleting its member and course rows, each with an audit entry.

    Args:
        group: the group to delete.
        actor: the user deleting it.
        reason: why (required, D40).

    Raises:
        ValidationError: if the reason is blank. Nothing is deleted.
    """
    with transaction.atomic():
        for row in group.members.all():
            audited_delete(row, actor, reason)
        for row in group.allowed_courses.all():
            audited_delete(row, actor, reason)
        audited_delete(group, actor, reason)


def preparation_from_loads(loads: Iterable[SubjectClassLoad]) -> Decimal:
    """Return the weekly preparation hours for weekly load rows (D61).

    Pass rows whose ``class_type`` is already loaded (``select_related`` or ``prefetch_related``)
    to avoid one query per row.

    Args:
        loads: the weekly hours rows of one subject.

    Returns:
        The preparation hours per week.
    """
    hours = {load.class_type.code: load.weekly_hours for load in loads}
    weights = {load.class_type.code: load.class_type.preparation_weight for load in loads}
    return preparation_hours(hours, weights)


def preparation_for(subject: Subject) -> Decimal:
    """Return the weekly preparation hours of a subject with the current weights (D61)."""
    return preparation_from_loads(subject.class_loads.select_related("class_type"))


def _numbers(rows) -> dict[int, dict[str, int]]:
    """Group enrollment rows as ``{turma id: {kind: students}}``."""
    grouped: dict[int, dict[str, int]] = {}
    for turma_id, kind, students in rows:
        grouped.setdefault(turma_id, {})[kind] = students
    return grouped


def class_group_size(group: ClassGroup, academic_year: AcademicYear) -> EffectiveStudents | None:
    """Return the number of students that counts for a turma in an academic year (D76).

    Args:
        group: the turma.
        academic_year: the academic year.

    Returns:
        The real number if it has arrived, otherwise the estimate marked as provisional;
        ``None`` if no number was entered.
    """
    rows = Enrollment.objects.filter(class_group=group, academic_year=academic_year).values_list(
        "class_group_id", "kind", "students"
    )
    numbers = _numbers(rows).get(group.pk, {})
    return effective_students(
        numbers.get(Enrollment.Kind.ESTIMATED), numbers.get(Enrollment.Kind.ACTUAL)
    )


def class_group_sizes(academic_year: AcademicYear) -> dict[int, EffectiveStudents]:
    """Return the number of students of every turma that has a number in an academic year.

    Args:
        academic_year: the academic year.

    Returns:
        A dictionary from turma id to the number that counts; turmas with no number are absent.
    """
    rows = Enrollment.objects.filter(academic_year=academic_year).values_list(
        "class_group_id", "kind", "students"
    )
    return {
        turma_id: effective_students(
            numbers.get(Enrollment.Kind.ESTIMATED), numbers.get(Enrollment.Kind.ACTUAL)
        )
        for turma_id, numbers in _numbers(rows).items()
    }
