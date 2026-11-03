"""Tests for the pure rules of the semester state (T2.2).

Implements: docs/backlog_fase2.md T2.2; D43, D86 – the whole table of moves.
"""

import pytest

from apps.dsd.lifecycle_rules import (
    ACTION_CLOSE,
    ACTION_OPEN,
    ACTION_REOPEN,
    CLOSED,
    NOT_OPENED,
    OPEN,
    needs_reason,
    next_state,
)


@pytest.mark.parametrize(
    ("current", "action", "expected"),
    [
        (NOT_OPENED, ACTION_OPEN, OPEN),
        (OPEN, ACTION_CLOSE, CLOSED),
        (CLOSED, ACTION_REOPEN, OPEN),
        # Everything else does not apply.
        (NOT_OPENED, ACTION_CLOSE, None),
        (NOT_OPENED, ACTION_REOPEN, None),
        (OPEN, ACTION_OPEN, None),
        (OPEN, ACTION_REOPEN, None),
        (CLOSED, ACTION_OPEN, None),
        (CLOSED, ACTION_CLOSE, None),
    ],
)
def test_the_table_of_moves(current, action, expected):
    """Opening starts, closing follows an opening, reopening follows a closing."""
    assert next_state(current, action) == expected


def test_an_unknown_action_is_an_error():
    """A typo must not silently mean "does not apply"."""
    with pytest.raises(ValueError):
        next_state(OPEN, "delete")


def test_only_opening_can_go_without_a_reason():
    """Closing and reopening change an existing state, so they need a reason (D40)."""
    assert not needs_reason(ACTION_OPEN)
    assert needs_reason(ACTION_CLOSE) and needs_reason(ACTION_REOPEN)
