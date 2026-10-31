"""Domain rules for cross-course subjects: group checks, warnings and suggestions.

Implements: docs/especificacao/04_modelo_de_dados.md – cross-course subjects (warning when
semester or load differ; suggestions of equivalent subjects); D22, D47.
Pure Python: no Django, no views, so the rules are easy to test and reuse.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher
from enum import StrEnum
from itertools import combinations

# Minimum name similarity (0-1) for a pair to be suggested. A parameter, not a business
# rule: the specification only says "similar name" (D47, to confirm).
DEFAULT_NAME_SIMILARITY = 0.8


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


@dataclass(frozen=True)
class Suggestion:
    """A pair of subjects the system suggests declaring equivalent (lower id first)."""

    subject_a: int
    subject_b: int
    score: float


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


def _normalise(name: str) -> str:
    """Lower-case a name and strip accents, so 'Introdução' matches 'INTRODUCAO'."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def _same_load(a: SubjectFacts, b: SubjectFacts) -> bool:
    """Return True if semester hours and the weekly split by class type are equal."""
    return a.semester_hours == b.semester_hours and dict(a.weekly_hours) == dict(b.weekly_hours)


def suggest_candidates(
    subjects: Iterable[SubjectFacts],
    rejected_pairs: Collection[tuple[int, int]],
    grouped_ids: Collection[int],
    threshold: float = DEFAULT_NAME_SIMILARITY,
) -> list[Suggestion]:
    """Suggest pairs of subjects that may be the same cross-course subject.

    A pair qualifies when the subjects are in different plans and different courses, the
    names are similar, and the ECTS or the load are equal (04_modelo_de_dados). Subjects
    already in a group and pairs the manager rejected are left out.

    Args:
        subjects: candidate subjects.
        rejected_pairs: pairs rejected before, in either order.
        grouped_ids: ids of subjects that already belong to a group.
        threshold: minimum name similarity, from 0 to 1.

    Returns:
        Suggestions ordered by descending score.
    """
    rejected = {tuple(sorted(pair)) for pair in rejected_pairs}
    result: list[Suggestion] = []
    for a, b in combinations(sorted(subjects, key=lambda s: s.id), 2):
        if a.id in grouped_ids or b.id in grouped_ids:
            continue
        if a.plan_id == b.plan_id or a.course_id == b.course_id:
            continue
        if (a.id, b.id) in rejected:
            continue
        score = SequenceMatcher(None, _normalise(a.name), _normalise(b.name)).ratio()
        if score < threshold:
            continue
        if a.ects == b.ects or _same_load(a, b):
            result.append(Suggestion(a.id, b.id, score))
    return sorted(result, key=lambda s: -s.score)
