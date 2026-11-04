"""Domain rule: annual teaching hours of a teacher and the range that applies to them.

Implements: docs/especificacao/05_dsd_regras.md – the range is measured in weekly lesson hours
summed over the two semesters, and it validates only the lesson hours (preparation and
non-teaching hours do not count); a range change applies from its date; D12, D58, D72.
Pure Python: no Django.

This module only gathers what the state of the load needs: the annual total, the detail of each
semester, and the range in force on a reference date. The four states and the extra hours are
computed from it later. The reference date is a parameter and is chosen by the caller: while the
DSD is open the range in force today applies, and a closed DSD keeps the values it was closed
with (05), which the closing task stores.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.staff.load_ranges import RangeRule, ResolvedRange, TeacherFacts, resolve_load_range

from .teaching_hours import SemesterTeachingHours

ZERO = Decimal("0")


@dataclass(frozen=True)
class AnnualTeachingHours:
    """Weekly teaching hours of a teacher in the two semesters of one academic year.

    Attributes:
        teacher_id: the teacher.
        semester_weekly_hours: weekly hours in the first and in the second semester.
        weekly_hours: the sum of the two semester totals, each already rounded to two decimals
            (D73), so the annual total is what the two shown totals add up to; it is the figure
            compared with the range (D12).
    """

    teacher_id: int
    semester_weekly_hours: tuple[Decimal, Decimal]
    weekly_hours: Decimal

    @classmethod
    def zero(cls, teacher_id: int) -> AnnualTeachingHours:
        """Return the record of a teacher with no hours in either semester.

        Args:
            teacher_id: the teacher.

        Returns:
            An all-zero record, so that a teacher without assignments is still compared with
            the minimum of their range.
        """
        return cls(teacher_id, (ZERO, ZERO), ZERO)


@dataclass(frozen=True)
class AnnualLoad:
    """The annual hours of a teacher with the range that applies to them.

    Attributes:
        teacher_id: the teacher.
        semester_weekly_hours: weekly hours in each semester.
        weekly_hours: the annual total.
        range: the range in force on ``as_of``, or ``None`` when no rule is in force for the
            teacher (a gap in the data, not an error).
        as_of: the reference date used to find the range.
    """

    teacher_id: int
    semester_weekly_hours: tuple[Decimal, Decimal]
    weekly_hours: Decimal
    range: ResolvedRange | None
    as_of: date


def annual_teaching_hours(
    first: SemesterTeachingHours, second: SemesterTeachingHours
) -> tuple[AnnualTeachingHours, ...]:
    """Add the weekly teaching hours of the two semesters, teacher by teacher.

    Args:
        first: the teaching hours of the first semester.
        second: the teaching hours of the second semester.

    Returns:
        One record per teacher who has hours in either semester, sorted by teacher id; the
        semester without hours counts as zero. Teachers with no hours at all are not listed:
        ask ``AnnualTeachingHours.zero`` for them.
    """
    ids = sorted({t.teacher_id for t in first.teachers} | {t.teacher_id for t in second.teachers})
    records = []
    for teacher_id in ids:
        one = first.for_teacher(teacher_id).weekly_hours
        two = second.for_teacher(teacher_id).weekly_hours
        records.append(AnnualTeachingHours(teacher_id, (one, two), one + two))
    return tuple(records)


def annual_load(
    hours: AnnualTeachingHours,
    rules: Iterable[RangeRule],
    teacher: TeacherFacts,
    as_of: date,
) -> AnnualLoad:
    """Join the annual hours of a teacher with the range in force on a date.

    Args:
        hours: the teacher's annual teaching hours.
        rules: every known range rule (any subject, any date).
        teacher: the teacher's type, category and positions.
        as_of: the date the range must be valid on.

    Returns:
        The annual load; ``range`` is ``None`` when no rule is in force.

    Raises:
        ValueError: for inconsistent range data (see ``resolve_load_range``).
    """
    return AnnualLoad(
        teacher_id=hours.teacher_id,
        semester_weekly_hours=hours.semester_weekly_hours,
        weekly_hours=hours.weekly_hours,
        range=resolve_load_range(rules, teacher, as_of),
        as_of=as_of,
    )
