"""Adapters between the academic models and the pure domain rules.

Implements: D47 – keeps ``cross_course`` free of Django.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .cross_course import SubjectFacts, effective_members
from .models import AcademicYear, ClassGroup, Course, CrossCourseSubject, StudyPlan, Subject
from .plans import PlanFacts, plan_in_force


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
) -> ClassGroup:
    """Create a turma with the plan in force for the first year of its intake (D48, D49).

    Args:
        course: course of the turma.
        intake_year: academic year in which the turma enters.
        label: letter to tell turmas of the same year apart; empty for the default turma.
        last_year: last academic year, if the turma already ended.

    Returns:
        The saved turma.

    Raises:
        ValidationError: if no plan of the course has reached the first year at the intake.
    """
    plans = [
        PlanFacts(id=p.pk, start_year=p.academic_year.start_year)
        for p in StudyPlan.objects.filter(course=course).select_related("academic_year")
    ]
    plan_id = plan_in_force(plans, 1, intake_year.start_year)
    if plan_id is None:
        raise ValidationError(_("Nenhum plano de estudos está em vigor para esta entrada."))
    return ClassGroup.objects.create(
        course=course,
        intake_year=intake_year,
        label=label,
        study_plan_id=plan_id,
        last_academic_year=last_year,
    )
