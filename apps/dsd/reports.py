"""Pure rules of the reports of the Executive Board (T6.8).

Implements: docs/especificacao/05_dsd_regras.md (the board has its own reports: teachers below the
minimum with their reasons, below the maximum, with extra hours); D16, D104.

No dependency on views or models. Each state of the annual load belongs to at most one report:
the teachers below the minimum, the teachers in range (below the maximum, with room for more
hours) and the teachers above the maximum (extra hours). A teacher at exactly the maximum, or with
no range in force, is in none.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from .extra_hours import ExtraStatus
from .load_status import LoadStatus
from .teaching_hours import round_hours

ZERO = Decimal("0")


class ReportKind(StrEnum):
    """The reports of the Executive Board."""

    BELOW_MINIMUM = "below_minimum"
    BELOW_MAXIMUM = "below_maximum"
    EXTRA_HOURS = "extra_hours"


def reports_of(status: LoadStatus, extra: ExtraStatus) -> set[ReportKind]:
    """Tell which reports a teacher appears in, from the state of their annual load.

    Args:
        status: the state of the annual load against the range (D72-D74).
        extra: whether the extra hours are accepted (kept for the report, not used to choose it).

    Returns:
        The reports: below the minimum, below the maximum (in range, with room left) or extra
        hours (above the maximum); empty at the maximum and with no range in force.
    """
    if status == LoadStatus.BELOW_MINIMUM:
        return {ReportKind.BELOW_MINIMUM}
    if status == LoadStatus.IN_RANGE:
        return {ReportKind.BELOW_MAXIMUM}
    if status == LoadStatus.ABOVE_MAXIMUM:
        return {ReportKind.EXTRA_HOURS}
    return set()


def free_hours(maximum: Decimal | None, hours: Decimal) -> Decimal | None:
    """Return the weekly hours a teacher can still take before the maximum of their range.

    Args:
        maximum: the maximum of the range, or ``None`` when no range is in force.
        hours: the annual teaching hours the teacher already has.

    Returns:
        The hours left, never negative, with two decimals; ``None`` without a range.
    """
    if maximum is None:
        return None
    return round_hours(max(maximum - hours, ZERO))
