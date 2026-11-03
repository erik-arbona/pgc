"""Pure rules of the semester state of a coordination (no Django).

Implements: docs/backlog_fase2.md T2.2; D43 (the PGC manager opens, closes and reopens).
A cell (semester x coordination) is not opened (``None``), open or closed. Opening is the first
move; closing only follows an opening; reopening only follows a closing. Anything else is "not
applicable", which the bulk operation reports as skipped instead of failing (D86).
"""

from __future__ import annotations

NOT_OPENED = None
OPEN = "open"
CLOSED = "closed"

ACTION_OPEN = "open"
ACTION_CLOSE = "close"
ACTION_REOPEN = "reopen"
ACTIONS = (ACTION_OPEN, ACTION_CLOSE, ACTION_REOPEN)

_TRANSITIONS: dict[tuple[str | None, str], str] = {
    (NOT_OPENED, ACTION_OPEN): OPEN,
    (OPEN, ACTION_CLOSE): CLOSED,
    (CLOSED, ACTION_REOPEN): OPEN,
}


def next_state(current: str | None, action: str) -> str | None:
    """Return the state after an action, or ``None`` if the action does not apply.

    Args:
        current: ``None`` (not opened), ``"open"`` or ``"closed"``.
        action: ``"open"``, ``"close"`` or ``"reopen"``.

    Returns:
        The new state, or ``None`` when the move is not allowed from ``current`` (for example
        closing a semester that was never opened, or opening one that is already open).

    Raises:
        ValueError: if ``action`` is unknown.
    """
    if action not in ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    return _TRANSITIONS.get((current, action))


def needs_reason(action: str) -> bool:
    """Tell whether the action needs a reason: closing and reopening change an existing state."""
    return action != ACTION_OPEN
