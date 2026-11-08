"""Pure rules of the view by course: hours counted once and indicators (T6.7).

Implements: docs/especificacao/07_arquitetura.md – view by course ("as suas horas contam uma só
vez nos totais gerais", indicators by course); D70 (a merge counts once), D103.

No dependency on views or models. A lesson shared by several courses appears in each of them,
but it is one lesson: the course that hosts the unit counts its hours and the others show it as a
guest row that adds nothing to the totals.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from .teaching_hours import round_hours

ZERO = Decimal("0")


@dataclass(frozen=True)
class RowFact:
    """What the totals need to know about one row of the view.

    Attributes:
        unit_id: the teaching unit.
        weekly_hours: its weekly hours, or ``None`` if its class type left the subject.
        category: the category of its teacher, or an empty text if it has none.
        teacher_id: its teacher, or ``None`` if nobody was given the unit yet.
        guest: the row only shows a lesson that another course hosts and counts.
    """

    unit_id: int
    weekly_hours: Decimal | None
    category: str
    teacher_id: int | None
    guest: bool


@dataclass(frozen=True)
class Indicators:
    """The indicators of a course.

    Attributes:
        hours_by_category: weekly hours given by each category of teacher.
        teachers: how many different teachers give lessons in the course.
        hours_without_teacher: weekly hours of the units nobody has been given.
    """

    hours_by_category: dict[str, Decimal]
    teachers: int
    hours_without_teacher: Decimal


def hours_counted_once(rows: Iterable[RowFact]) -> Decimal:
    """Add the weekly hours of the lessons the course hosts, leaving out the guest rows.

    Args:
        rows: the rows of the view.

    Returns:
        The total, with two decimals. Each unit counts once, so N groups count N times (D90).
    """
    return round_hours(sum((row.weekly_hours or ZERO for row in rows if not row.guest), ZERO))


def indicators(rows: Iterable[RowFact]) -> Indicators:
    """Compute the indicators of a course from its rows, counting every lesson once.

    Args:
        rows: the rows of the view.

    Returns:
        Hours by category of teacher, the number of different teachers and the hours still
        without a teacher. Guest rows are ignored: the hosting course counts them.
    """
    by_category: dict[str, Decimal] = {}
    teachers: set[int] = set()
    without = ZERO
    for row in rows:
        if row.guest:
            continue
        hours = row.weekly_hours or ZERO
        if row.teacher_id is None:
            without += hours
            continue
        teachers.add(row.teacher_id)
        by_category[row.category] = by_category.get(row.category, ZERO) + hours
    return Indicators(
        hours_by_category={name: round_hours(value) for name, value in by_category.items()},
        teachers=len(teachers),
        hours_without_teacher=round_hours(without),
    )
