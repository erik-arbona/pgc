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
) -> list[str]:
    """Return the blocking errors of a group (empty when it is valid).

    A group needs at least two different courses among its members, and the courses in which
    it is cross-course must be courses of its members (D22). They may be fewer than the
    members' courses: a subject can be declared in two courses and refused in a third.

    Args:
        members: the subjects of the group.
        allowed_course_ids: courses in which classes of the subject may be merged.

    Returns:
        A list of error messages in English; the caller translates them for the interface.
    """
    member_courses = {m.course_id for m in members}
    allowed = set(allowed_course_ids)
    errors: list[str] = []
    if len(member_courses) < 2:
        errors.append("A cross-course subject needs members from at least two courses.")
    if len(allowed) < 2:
        errors.append("At least two courses must be allowed.")
    if not allowed <= member_courses:
        errors.append("Allowed courses must be courses of the group's members.")
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
