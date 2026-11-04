"""Hours of the non-teaching component of a teacher (T5.3).

Implements: docs/especificacao/05_dsd_regras.md – non-teaching component; D15, D95.

Pure rules, with no dependency on views or models. The annual range only validates the teaching
hours; the other activities and the preparation are added to the general total of the teacher and
never count towards the range.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from .teaching_hours import round_hours

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class ActivityFact:
    """One activity of a teacher in a semester.

    Attributes:
        teacher_id: the teacher.
        semester_number: 1 or 2.
        weekly_hours: weekly hours of the activity, as the teaching hours are measured.
    """

    teacher_id: int
    semester_number: int
    weekly_hours: Decimal


def other_hours_by_teacher(
    facts: Iterable[ActivityFact],
) -> dict[int, tuple[Decimal, Decimal]]:
    """Add the weekly hours of the activities of each teacher, by semester.

    Args:
        facts: the activities of any number of teachers.

    Returns:
        ``{teacher id: (first semester hours, second semester hours)}`` for the teachers who have
        activities; ask with a default of ``(0, 0)`` for the others.

    Raises:
        ValueError: if a semester number is not 1 or 2.
    """
    totals: dict[int, list[Decimal]] = {}
    for fact in facts:
        if fact.semester_number not in (1, 2):
            raise ValueError(f"Invalid semester number: {fact.semester_number}")
        pair = totals.setdefault(fact.teacher_id, [ZERO, ZERO])
        pair[fact.semester_number - 1] += fact.weekly_hours
    return {
        teacher_id: (round_hours(pair[0]), round_hours(pair[1]))
        for teacher_id, pair in totals.items()
    }


def general_total(
    teaching: Decimal, preparation: tuple[Decimal, Decimal], other: tuple[Decimal, Decimal]
) -> Decimal:
    """Return the general weekly total of a teacher over the two semesters (D95).

    The total is the annual teaching hours, plus the preparation of both semesters, plus the
    hours of the other activities of both semesters. Only the teaching hours are compared with
    the range of the teacher.

    Args:
        teaching: the annual teaching hours (the sum of the two semesters).
        preparation: the weekly preparation hours of each semester.
        other: the weekly hours of the other activities of each semester.

    Returns:
        The total, with two decimals.
    """
    return round_hours(teaching + preparation[0] + preparation[1] + other[0] + other[1])
