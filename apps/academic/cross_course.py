"""Domain rules for cross-course subjects: group checks and warnings.

Implements: docs/especificacao/04_modelo_de_dados.md – cross-course subjects (warning when
semester or load differ); D22, D47. The system does not suggest equivalent subjects: the
manager finds them (D47).
Pure Python: no Django, no views, so the rules are easy to test and reuse.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from .plans import PlanFacts, plan_in_force


@dataclass(frozen=True)
class SubjectFacts:
    """The facts about a subject that the cross-course rules need.

    Attributes:
        id: subject primary key.
        course_id: course of the subject's study plan.
        plan_id: study plan of the subject.
        name: subject name.
        ects: ECTS credits.
        semester: semester (1 or 2).
        curricular_year: year of the course in which the subject is taught.
        semester_hours: total hours in the semester.
        weekly_hours: weekly hours by class type code.
    """

    id: int
    course_id: int
    plan_id: int
    name: str
    ects: Decimal
    semester: int
    semester_hours: Decimal
    weekly_hours: Mapping[str, Decimal] = field(default_factory=dict)
    curricular_year: int = 1


class GroupError(StrEnum):
    """Reasons why a group is not valid (blocking)."""

    TOO_FEW_COURSES = "too_few_courses"
    TOO_FEW_ALLOWED = "too_few_allowed"
    ALLOWED_NOT_IN_MEMBERS = "allowed_not_in_members"


class WarningKind(StrEnum):
    """Kinds of difference between the members of a group."""

    SEMESTER_DIFFERS = "semester_differs"
    SEMESTER_HOURS_DIFFER = "semester_hours_differ"
    CLASS_LOAD_DIFFERS = "class_load_differs"


@dataclass(frozen=True)
class CrossCourseWarning:
    """A non-blocking warning about a group.

    Attributes:
        kind: what differs.
        detail: the class type code for ``CLASS_LOAD_DIFFERS``, otherwise empty.
    """

    kind: WarningKind
    detail: str = ""


def check_group(
    members: Collection[SubjectFacts], allowed_course_ids: Collection[int]
) -> list[GroupError]:
    """Return the blocking errors of a group (empty when it is valid).

    A group needs at least two different courses among its members, and the courses in which
    it is cross-course must be courses of its members (D22). They may be fewer than the
    members' courses: a subject can be declared in two courses and refused in a third.

    Args:
        members: the subjects of the group.
        allowed_course_ids: courses in which classes of the subject may be merged.

    Returns:
        The error codes, empty when the group is valid; the interface maps them to texts.
    """
    member_courses = {m.course_id for m in members}
    allowed = set(allowed_course_ids)
    errors: list[GroupError] = []
    if len(member_courses) < 2:
        errors.append(GroupError.TOO_FEW_COURSES)
    if len(allowed) < 2:
        errors.append(GroupError.TOO_FEW_ALLOWED)
    if not allowed <= member_courses:
        errors.append(GroupError.ALLOWED_NOT_IN_MEMBERS)
    return errors


def compare_members(members: Collection[SubjectFacts]) -> list[CrossCourseWarning]:
    """Return a warning for each difference of semester or load between members.

    Differences do not block the group: such classes just cannot be merged (04_modelo_de_dados).

    Args:
        members: the subjects of the group.

    Returns:
        The warnings, empty when the members agree.
    """
    items = list(members)
    warnings: list[CrossCourseWarning] = []
    if len({m.semester for m in items}) > 1:
        warnings.append(CrossCourseWarning(WarningKind.SEMESTER_DIFFERS))
    if len({m.semester_hours for m in items}) > 1:
        warnings.append(CrossCourseWarning(WarningKind.SEMESTER_HOURS_DIFFER))
    class_types = sorted({code for m in items for code in m.weekly_hours})
    for code in class_types:
        # A class type missing on one side counts as a difference (zero hours there).
        if len({m.weekly_hours.get(code, Decimal("0")) for m in items}) > 1:
            warnings.append(CrossCourseWarning(WarningKind.CLASS_LOAD_DIFFERS, code))
    return warnings


def effective_members(
    members: Collection[SubjectFacts],
    plans_by_course: Mapping[int, Collection[PlanFacts]],
    academic_year: int,
) -> list[SubjectFacts]:
    """Return the members that count in an academic year.

    A member counts only while its plan is the one in force for its curricular year (D48):
    once a new plan reaches that year, the old plan's subject stops counting, without being
    removed from the group. The manager adds the new plan's subjects by hand.

    Args:
        members: the subjects recorded in the group.
        plans_by_course: all study plans of each course, keyed by course id.
        academic_year: start year of the academic year.

    Returns:
        The members whose plan is in force, in the original order.
    """
    return [
        m
        for m in members
        if plan_in_force(plans_by_course.get(m.course_id, ()), m.curricular_year, academic_year)
        == m.plan_id
    ]
