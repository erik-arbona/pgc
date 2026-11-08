"""Data of the view by course: the lessons of a course across coordinations (T6.7).

Implements: docs/especificacao/07_arquitetura.md – view by course; D20, D47, D70, D92, D103.

Adapter between the models and the pure rules in ``course_rules``. It reads, for one DSD and one
course, every teaching unit of the subjects of the course (whatever the coordination), the turmas
of the course that were merged into a unit of another subject (shown as guest rows that add
nothing to the totals), the transversal subjects (marked as shared), and the subjects of the plan
in force that no turma attends. The filters are applied in Python over the whole set, which is
small, so that the options of the filters always come from the unfiltered data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q

from apps.academic.models import ClassGroup, ClassType, Course, CrossCourseSubjectMember, Subject
from apps.staff.models import Teacher

from .course_rules import Indicators, RowFact, hours_counted_once, indicators
from .models import Dsd, Offering, TeachingUnit, TeachingUnitMember


@dataclass(frozen=True)
class CourseFilters:
    """The combinable filters of the view; ``None`` means no filter.

    Attributes:
        semester: 1 or 2.
        curricular_year: the curricular year of the subject.
        class_type: the code of the class type (T, P, ...).
        teacher_id: the teacher of the unit.
        class_group_id: a turma that attends the unit.
    """

    semester: int | None = None
    curricular_year: int | None = None
    class_type: str | None = None
    teacher_id: int | None = None
    class_group_id: int | None = None


@dataclass
class LessonRow:
    """One row of the view: a lesson of a subject of the course.

    Attributes:
        subject: the subject of the course this row is about.
        unit: the teaching unit that gives the lesson.
        class_type: the code of its class type.
        groups: the turmas or groups it is given to.
        class_group_ids: the ids of those turmas.
        teacher: its teacher, or ``None``.
        weekly_hours: its weekly hours in the subject that hosts it.
        shared: the subject belongs to a transversal group (D47).
        guest: the lesson is hosted by a unit of another subject: shown here, counted there.
        host_subject: the subject that hosts a guest lesson.
        semester_number: 1 or 2.
        curricular_year: the curricular year of the subject.
    """

    subject: Subject
    unit: TeachingUnit
    class_type: str
    groups: list[str]
    class_group_ids: set[int]
    teacher: Teacher | None
    weekly_hours: Decimal | None
    shared: bool
    guest: bool = False
    host_subject: Subject | None = None
    semester_number: int = 1
    curricular_year: int = 1

    @property
    def without_teacher(self) -> bool:
        """Whether nobody has been given the lesson yet."""
        return self.teacher is None


@dataclass
class CourseData:
    """What the view by course shows.

    Attributes:
        course: the course.
        rows: the lessons after the filters.
        without_turma: the subjects of the plan in force that no turma attends.
        total_hours: the weekly hours the course hosts, each lesson counted once.
        indicators: hours by category of teacher and number of teachers.
        options: the values the filters can take, from the unfiltered data.
    """

    course: Course
    rows: list[LessonRow]
    without_turma: list[Subject]
    total_hours: Decimal
    indicators: Indicators
    options: dict[str, list] = field(default_factory=dict)


def _hours(unit: TeachingUnit) -> Decimal | None:
    """The weekly hours of a unit: those of its class type in the subject that hosts it (D92)."""
    return next(
        (
            load.weekly_hours
            for load in unit.offering.subject.class_loads.all()
            if load.class_type_id == unit.class_type_id
        ),
        None,
    )


def _label(member: TeachingUnitMember) -> str:
    """The turma or group a member stands for, as the screens print it."""
    return str(member.subgroup if member.subgroup_id else member.class_group_link.class_group)


def _matches(row: LessonRow, filters: CourseFilters) -> bool:
    """Whether a row passes every filter that is set."""
    return (
        (filters.semester is None or row.semester_number == filters.semester)
        and (filters.curricular_year is None or row.curricular_year == filters.curricular_year)
        and (filters.class_type is None or row.class_type == filters.class_type)
        and (filters.teacher_id is None or (row.teacher and row.teacher.pk == filters.teacher_id))
        and (filters.class_group_id is None or filters.class_group_id in row.class_group_ids)
    )


def course_view(dsd: Dsd, course: Course, filters: CourseFilters | None = None) -> CourseData:
    """Build the view of a course in a DSD, reading every coordination that teaches it.

    Args:
        dsd: the DSD.
        course: the course.
        filters: the filters to apply; none by default.

    Returns:
        The rows, what is missing, the hours counted once, the indicators and the options.
    """
    filters = filters or CourseFilters()
    in_dsd = Q(offering__dsd_semester__dsd=dsd)
    units = (
        TeachingUnit.objects.filter(in_dsd, offering__subject__study_plan__course=course)
        .select_related(
            "class_type",
            "teacher__category",
            "offering__subject__coordination",
            "offering__subject__study_plan",
            "offering__dsd_semester",
        )
        .prefetch_related(
            "offering__subject__class_loads",
            "members__class_group_link__class_group__course",
            "members__class_group_link__class_group__track",
            "members__subgroup__class_group_link__class_group__course",
            "members__subgroup__class_group_link__class_group__track",
        )
        .order_by(
            "offering__subject__curricular_year",
            "offering__dsd_semester__number",
            "offering__subject__code",
            "class_type__position",
            "pk",
        )
    )
    shared_ids = set(
        CrossCourseSubjectMember.objects.filter(subject__study_plan__course=course).values_list(
            "subject_id", flat=True
        )
    )
    rows: list[LessonRow] = []
    for unit in units:
        subject = unit.offering.subject
        members = list(unit.members.all())
        rows.append(
            LessonRow(
                subject=subject,
                unit=unit,
                class_type=unit.class_type.code,
                groups=[_label(member) for member in members],
                class_group_ids={member.turma_link.class_group_id for member in members},
                teacher=unit.teacher,
                weekly_hours=_hours(unit),
                shared=subject.pk in shared_ids,
                semester_number=unit.offering.dsd_semester.number,
                curricular_year=subject.curricular_year,
            )
        )
    rows += _guest_rows(dsd, course, shared_ids)
    visible = [row for row in rows if _matches(row, filters)]
    facts = [
        RowFact(
            row.unit.pk,
            row.weekly_hours,
            row.teacher.category.name if row.teacher else "",
            row.teacher.pk if row.teacher else None,
            row.guest,
        )
        for row in visible
    ]
    return CourseData(
        course=course,
        rows=visible,
        without_turma=_without_turma(dsd, course, filters),
        total_hours=hours_counted_once(facts),
        indicators=indicators(facts),
        options=_options(rows, course),
    )


def _guest_rows(dsd: Dsd, course: Course, shared_ids: set[int]) -> list[LessonRow]:
    """The lessons of turmas of this course that a unit of another subject hosts (D92)."""
    own = Q(class_group_link__offering__subject__study_plan__course=course) | Q(
        subgroup__class_group_link__offering__subject__study_plan__course=course
    )
    members = (
        TeachingUnitMember.objects.filter(own, unit__offering__dsd_semester__dsd=dsd)
        .select_related(
            "unit__class_type",
            "unit__teacher__category",
            "unit__offering__subject__coordination",
            "unit__offering__subject__study_plan",
            "unit__offering__dsd_semester",
            "class_group_link__offering__subject",
            "class_group_link__class_group__course",
            "class_group_link__class_group__track",
            "subgroup__class_group_link__offering__subject",
            "subgroup__class_group_link__class_group__course",
            "subgroup__class_group_link__class_group__track",
        )
        .prefetch_related("unit__offering__subject__class_loads")
    )
    rows = []
    for member in members:
        link = member.turma_link
        if link.offering_id == member.unit.offering_id:
            continue  # the unit belongs to this very offering: not a guest
        subject = link.offering.subject
        rows.append(
            LessonRow(
                subject=subject,
                unit=member.unit,
                class_type=member.unit.class_type.code,
                groups=[_label(member)],
                class_group_ids={link.class_group_id},
                teacher=member.unit.teacher,
                weekly_hours=_hours(member.unit),
                shared=subject.pk in shared_ids,
                guest=True,
                host_subject=member.unit.offering.subject,
                semester_number=member.unit.offering.dsd_semester.number,
                curricular_year=subject.curricular_year,
            )
        )
    return rows


def _without_turma(dsd: Dsd, course: Course, filters: CourseFilters) -> list[Subject]:
    """The subjects of the plan in force that no turma attends in this DSD (no offering).

    Narrowing the view to a teacher, a class type or a turma is about lessons, not about plan
    subjects, so the list is empty then.
    """
    if filters.teacher_id is not None or filters.class_type or filters.class_group_id is not None:
        return []
    year = dsd.academic_year.start_year
    plan = (
        course.study_plans.filter(academic_year__start_year__lte=year)
        .order_by("-academic_year__start_year")
        .first()
    )
    if plan is None:
        return []
    with_offering = Offering.objects.filter(dsd_semester__dsd=dsd).values_list(
        "subject_id", flat=True
    )
    subjects = plan.subjects.exclude(pk__in=with_offering)
    if filters.semester is not None:
        subjects = subjects.filter(semester=filters.semester)
    if filters.curricular_year is not None:
        subjects = subjects.filter(curricular_year=filters.curricular_year)
    return list(subjects.order_by("curricular_year", "semester", "code"))


def _options(rows: list[LessonRow], course: Course) -> dict[str, list]:
    """The values the filters can take, taken from the unfiltered rows and the course."""
    teachers = {row.teacher.pk: row.teacher for row in rows if row.teacher}
    return {
        "semesters": sorted({row.semester_number for row in rows}),
        "years": sorted({row.curricular_year for row in rows}),
        "class_types": [
            code
            for code in ClassType.objects.order_by("position").values_list("code", flat=True)
            if any(row.class_type == code for row in rows)
        ],
        "teachers": sorted(teachers.values(), key=lambda teacher: teacher.name),
        "class_groups": list(
            ClassGroup.objects.filter(course=course).order_by("intake_year", "label")
        ),
    }
