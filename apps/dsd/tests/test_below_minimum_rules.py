"""Tests for the pure rule of the reason for a load below the minimum (T5.5).

Implements: docs/especificacao/05_dsd_regras.md – below the minimum; D16, D97.
"""

from apps.dsd.below_minimum import MinimumReasonState, minimum_reason_state


def test_a_teacher_not_below_the_minimum_needs_no_reason():
    """Whatever was recorded, nothing is needed when the load is not below the minimum."""
    assert minimum_reason_state(False, None, None, None) == MinimumReasonState.NOT_NEEDED
    assert minimum_reason_state(False, 1, 1, "refused") == MinimumReasonState.NOT_NEEDED


def test_below_the_minimum_without_a_reason_is_missing():
    """The coordinator has to register one."""
    assert minimum_reason_state(True, None, None, None) == MinimumReasonState.MISSING


def test_a_reason_nobody_reviewed_is_pending():
    """Registered, waiting for the Executive Board."""
    assert minimum_reason_state(True, 1, None, None) == MinimumReasonState.PENDING


def test_an_accepted_reason_is_accepted():
    """The review is of the current version of the reason."""
    assert minimum_reason_state(True, 2, 2, "accepted") == MinimumReasonState.ACCEPTED


def test_a_refused_reason_is_refused():
    """The case goes back to the coordinator."""
    assert minimum_reason_state(True, 2, 2, "refused") == MinimumReasonState.REFUSED


def test_a_reason_changed_after_the_review_is_pending_again():
    """The review was of version 2; the text is now version 3 (D40, D97)."""
    assert minimum_reason_state(True, 3, 2, "refused") == MinimumReasonState.PENDING
    assert minimum_reason_state(True, 3, 2, "accepted") == MinimumReasonState.PENDING
