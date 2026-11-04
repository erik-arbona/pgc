"""State of the reason for a teacher whose load is below the minimum (T5.5).

Implements: docs/especificacao/05_dsd_regras.md – below the minimum; D16, D97.

Pure rule, with no dependency on views or models. Below the minimum the coordinator registers a
reason; the Executive Board accepts or refuses it. A review belongs to one version of the reason
text, so changing the text after a review makes it pending again.
"""

from __future__ import annotations

from enum import StrEnum

ACCEPTED = "accepted"
REFUSED = "refused"
DECISIONS = (ACCEPTED, REFUSED)


class MinimumReasonState(StrEnum):
    """Where the reason of a teacher below the minimum stands."""

    NOT_NEEDED = "not_needed"  # the load is not below the minimum
    MISSING = "missing"  # below the minimum and the coordinator has not given a reason
    PENDING = "pending"  # a reason nobody has reviewed (or changed after the review)
    ACCEPTED = "accepted"  # the Executive Board accepted this version of the reason
    REFUSED = "refused"  # the Executive Board refused it: back to the coordinator


def minimum_reason_state(
    below_minimum: bool,
    reason_version: int | None,
    review_version: int | None,
    decision: str | None,
) -> MinimumReasonState:
    """Tell where the reason of a teacher stands (D16, D97).

    Args:
        below_minimum: whether the annual load is below the minimum of the range.
        reason_version: the version of the reason text, or ``None`` if none was registered.
        review_version: the version of the text the Executive Board reviewed, or ``None``.
        decision: ``"accepted"`` or ``"refused"``, or ``None`` if there is no review.

    Returns:
        The state. A review of an older version of the text does not count.
    """
    if not below_minimum:
        return MinimumReasonState.NOT_NEEDED
    if reason_version is None:
        return MinimumReasonState.MISSING
    if review_version != reason_version or decision not in DECISIONS:
        return MinimumReasonState.PENDING
    return MinimumReasonState.ACCEPTED if decision == ACCEPTED else MinimumReasonState.REFUSED
