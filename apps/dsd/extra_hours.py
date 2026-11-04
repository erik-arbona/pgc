"""State of the extra hours of a teacher against what they accepted (T5.4).

Implements: docs/especificacao/05_dsd_regras.md – extra hours; D13, D96.

Pure rule, with no dependency on views or models. The extra hours are the excess of the annual
teaching hours over the maximum of the range (computed in ``load_status``); they are only
legitimate if the teacher accepts them, and the coordinator records how many hours were accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .teaching_hours import round_hours


class ExtraStatus(StrEnum):
    """Whether the extra hours of a teacher are covered by their acceptance."""

    NONE = "none"  # no excess: nothing to accept
    ACCEPTED = "accepted"  # the accepted hours cover the whole excess
    PENDING = "pending"  # part of the excess (or all of it) is not accepted yet


@dataclass(frozen=True)
class ExtraAssessment:
    """The extra hours of a teacher, the hours they accepted and what is still pending.

    Attributes:
        status: whether the excess is covered.
        extra_hours: the excess over the maximum (zero when there is none).
        accepted_hours: the hours the teacher accepted, as recorded (zero when none).
        pending_hours: the part of the excess not covered by the acceptance.
    """

    status: ExtraStatus
    extra_hours: Decimal
    accepted_hours: Decimal
    pending_hours: Decimal


def assess_extra(extra_hours: Decimal, accepted_hours: Decimal) -> ExtraAssessment:
    """Compare the extra hours of a teacher with the hours they accepted (D13, D96).

    An acceptance of 4 hours covers an excess of 4 or less; with an excess of 6, 2 hours stay
    pending. Without an excess there is nothing to accept, whatever was recorded: the record is
    kept and simply does not matter.

    Args:
        extra_hours: the excess over the maximum, zero or more.
        accepted_hours: the hours the teacher accepted, zero when nothing is recorded.

    Returns:
        The assessment, with the hours rounded to two decimals.
    """
    extra = round_hours(extra_hours)
    accepted = round_hours(accepted_hours)
    if extra <= 0:
        return ExtraAssessment(ExtraStatus.NONE, extra, accepted, round_hours(Decimal("0")))
    pending = round_hours(max(extra - accepted, Decimal("0")))
    status = ExtraStatus.PENDING if pending > 0 else ExtraStatus.ACCEPTED
    return ExtraAssessment(status, extra, accepted, pending)
