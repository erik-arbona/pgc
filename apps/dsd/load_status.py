"""Domain rule: state of the annual load of a teacher and their extra hours.

Implements: docs/especificacao/05_dsd_regras.md – the four states of the annual load against the
range (below the minimum, in the range, at the maximum, above the maximum) and the extra hours
(total of lesson hours minus the maximum, D13); the minimum is optional (D46); D12, D58, D73, D74.
Pure Python: no Django.

The comparison uses the annual total already rounded to two decimals (D73), so a teacher whose
exact total is 15.9984 shows 16.00 and is *at* the maximum, without crumbs like 15.9999.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from apps.staff.load_ranges import ResolvedRange

from .annual_load import AnnualLoad

ZERO = Decimal("0")


class LoadStatus(StrEnum):
    """The state of the annual load of a teacher."""

    BELOW_MINIMUM = "below_minimum"  # needs a reason from the coordinator (T5.5)
    IN_RANGE = "in_range"  # reached the minimum and not yet the maximum
    AT_MAXIMUM = "at_maximum"  # at the limit: any further hour is extra
    ABOVE_MAXIMUM = "above_maximum"  # extra hours, only if the teacher accepts them (T5.4)
    NO_RANGE = "no_range"  # no range rule in force: a gap in the data, not an error


@dataclass(frozen=True)
class LoadAssessment:
    """What the interface and the alerts need to know about a teacher's annual load.

    Attributes:
        teacher_id: the teacher.
        status: the state of the load.
        extra_hours: total minus the maximum when above it, otherwise zero. It is the amount
            that would be extra; whether the teacher accepts it is recorded elsewhere (D13).
        weekly_hours: the annual total, rounded to two decimals.
        semester_weekly_hours: the detail of each semester.
        range: the range used, or ``None`` when no rule was in force.
        as_of: the reference date of the range.
    """

    teacher_id: int
    status: LoadStatus
    extra_hours: Decimal
    weekly_hours: Decimal
    semester_weekly_hours: tuple[Decimal, Decimal]
    range: ResolvedRange | None
    as_of: date


def assess_load(load: AnnualLoad) -> LoadAssessment:
    """Return the state of a teacher's annual load and the extra hours.

    The rules, with ``H`` the annual total, ``m`` the optional minimum and ``M`` the maximum:
    no range gives ``NO_RANGE``; ``H > M`` is ``ABOVE_MAXIMUM``; ``H = M`` is ``AT_MAXIMUM`` (also
    when ``m = M``); a minimum exists and ``H < m`` is ``BELOW_MINIMUM``; anything else
    (``m <= H < M``, or any ``H < M`` without a minimum) is ``IN_RANGE``. Without a minimum a
    teacher is never below it, not even with no hours (D46).

    Args:
        load: the annual hours with the range in force.

    Returns:
        The assessment, with the extra hours (``H - M`` above the maximum, otherwise zero).
    """
    hours = load.weekly_hours
    resolved = load.range
    extra = ZERO
    if resolved is None:
        status = LoadStatus.NO_RANGE
    elif hours > resolved.maximum:
        status = LoadStatus.ABOVE_MAXIMUM
        extra = hours - resolved.maximum
    elif hours == resolved.maximum:
        status = LoadStatus.AT_MAXIMUM
    elif resolved.minimum is not None and hours < resolved.minimum:
        status = LoadStatus.BELOW_MINIMUM
    else:
        status = LoadStatus.IN_RANGE
    return LoadAssessment(
        teacher_id=load.teacher_id,
        status=status,
        extra_hours=extra,
        weekly_hours=hours,
        semester_weekly_hours=load.semester_weekly_hours,
        range=resolved,
        as_of=load.as_of,
    )
