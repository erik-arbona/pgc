"""State machine of a tender proposal (block 5).

Implements: docs/especificacao/05_dsd_regras.md – tender proposals; D17, D46, D105.

Pure rules, with no dependency on views or models. The coordinator proposes a unit that no
teacher of the coordination can take; the Executive Board refuses it (back to the coordinator) or
approves it and then invites a collaborator or launches the tender; the board records the answer
of the invited teacher; and the unit is finally filled by the coordinator (an accepted
collaborator) or by the PGC manager (the teacher obtained by tender).
"""

from __future__ import annotations

from enum import StrEnum


class TenderState(StrEnum):
    """Where a proposal stands."""

    PROPOSED = "proposed"  # waiting for the Executive Board
    REFUSED = "refused"  # the board refused it: back to the coordinator
    APPROVED = "approved"  # the board approved it: invite a collaborator or launch the tender
    INVITED = "invited"  # a collaborator was invited and has not answered
    ACCEPTED = "accepted"  # the collaborator accepted: the coordinator assigns them
    TENDER = "tender"  # «A concurso»: waiting for the teacher the tender obtains
    FILLED = "filled"  # the unit has its teacher
    WITHDRAWN = "withdrawn"  # the coordinator withdrew it


class TenderAction(StrEnum):
    """What can be done to a proposal."""

    RESUBMIT = "resubmit"  # coordinator: treats a refused proposal again
    WITHDRAW = "withdraw"  # coordinator
    REFUSE = "refuse"  # board
    APPROVE = "approve"  # board
    INVITE = "invite"  # board: invites a collaborator
    SEND_TO_TENDER = "send_to_tender"  # board: launches the tender
    ACCEPT_INVITATION = "accept_invitation"  # board records the teacher's answer: yes
    DECLINE_INVITATION = "decline_invitation"  # board records the answer: no (D46)
    FILL = "fill"  # the unit is given its teacher
    CANCEL = "cancel"  # board: closes a case that cannot go on (the collaborator left...)


# action -> {state it can be done from: state it leads to}
_TRANSITIONS: dict[TenderAction, dict[TenderState, TenderState]] = {
    TenderAction.RESUBMIT: {TenderState.REFUSED: TenderState.PROPOSED},
    TenderAction.WITHDRAW: {
        TenderState.PROPOSED: TenderState.WITHDRAWN,
        TenderState.REFUSED: TenderState.WITHDRAWN,
        TenderState.APPROVED: TenderState.WITHDRAWN,
    },
    TenderAction.REFUSE: {TenderState.PROPOSED: TenderState.REFUSED},
    TenderAction.APPROVE: {TenderState.PROPOSED: TenderState.APPROVED},
    TenderAction.INVITE: {TenderState.APPROVED: TenderState.INVITED},
    TenderAction.SEND_TO_TENDER: {TenderState.APPROVED: TenderState.TENDER},
    TenderAction.ACCEPT_INVITATION: {TenderState.INVITED: TenderState.ACCEPTED},
    TenderAction.DECLINE_INVITATION: {TenderState.INVITED: TenderState.TENDER},
    TenderAction.FILL: {
        TenderState.ACCEPTED: TenderState.FILLED,
        TenderState.TENDER: TenderState.FILLED,
    },
    # A dead case must have an exit: the board can close it from any open state.
    TenderAction.CANCEL: {
        state: TenderState.WITHDRAWN
        for state in TenderState
        if state not in (TenderState.FILLED, TenderState.WITHDRAWN)
    },
}

# A proposal holds its unit until it is filled or withdrawn.
OPEN_STATES = set(TenderState) - {TenderState.FILLED, TenderState.WITHDRAWN}


def next_state(state: TenderState, action: TenderAction) -> TenderState:
    """Return the state a proposal moves to when an action is done.

    Args:
        state: where the proposal stands.
        action: what is done.

    Returns:
        The new state.

    Raises:
        ValueError: if the action cannot be done from that state.
    """
    try:
        return _TRANSITIONS[action][state]
    except KeyError:
        raise ValueError(f"Cannot {action.value} a proposal that is {state.value}.") from None


def needs_comment(action: TenderAction) -> bool:
    """Tell whether an action needs a comment: a refusal (what is missing) or a cancellation.

    Args:
        action: what is done.

    Returns:
        True for a refusal and for a cancellation.
    """
    return action in (TenderAction.REFUSE, TenderAction.CANCEL)
