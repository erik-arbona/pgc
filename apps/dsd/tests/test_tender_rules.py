"""Tests for the state machine of a tender proposal (block 5).

Implements: docs/especificacao/05_dsd_regras.md – tender proposals; D17, D46, D105.
"""

import pytest

from apps.dsd.tender_rules import (
    OPEN_STATES,
    TenderAction,
    TenderState,
    needs_comment,
    next_state,
)


def test_a_new_proposal_waits_for_the_board_and_the_board_can_refuse_or_approve():
    """Proposed: refuse sends it back to the coordinator, approve opens the choices."""
    assert next_state(TenderState.PROPOSED, TenderAction.REFUSE) == TenderState.REFUSED
    assert next_state(TenderState.PROPOSED, TenderAction.APPROVE) == TenderState.APPROVED


def test_a_refused_proposal_goes_back_to_the_board_when_the_coordinator_treats_it_again():
    """The coordinator corrects the justification and sends it again (05)."""
    assert next_state(TenderState.REFUSED, TenderAction.RESUBMIT) == TenderState.PROPOSED


def test_an_approved_proposal_becomes_an_invitation_or_a_tender():
    """The board invites a collaborator or launches the tender."""
    assert next_state(TenderState.APPROVED, TenderAction.INVITE) == TenderState.INVITED
    assert next_state(TenderState.APPROVED, TenderAction.SEND_TO_TENDER) == TenderState.TENDER


def test_the_answer_to_an_invitation_accepts_or_sends_the_unit_to_the_tender():
    """If the teacher or the board refuses, the subject goes to tender (D46)."""
    assert next_state(TenderState.INVITED, TenderAction.ACCEPT_INVITATION) == TenderState.ACCEPTED
    assert next_state(TenderState.INVITED, TenderAction.DECLINE_INVITATION) == TenderState.TENDER


def test_the_unit_is_filled_after_an_accepted_invitation_or_a_tender():
    """The coordinator assigns the accepted collaborator; the manager registers the winner."""
    assert next_state(TenderState.ACCEPTED, TenderAction.FILL) == TenderState.FILLED
    assert next_state(TenderState.TENDER, TenderAction.FILL) == TenderState.FILLED


def test_the_coordinator_may_withdraw_until_the_invitation_goes_out():
    """Proposed, refused or approved: withdrawn. After that the board owns the case."""
    for state in (TenderState.PROPOSED, TenderState.REFUSED, TenderState.APPROVED):
        assert next_state(state, TenderAction.WITHDRAW) == TenderState.WITHDRAWN
    for state in (TenderState.INVITED, TenderState.ACCEPTED, TenderState.TENDER):
        with pytest.raises(ValueError):
            next_state(state, TenderAction.WITHDRAW)


def test_an_action_out_of_order_is_refused():
    """Each action is valid from its own states only."""
    cases = [
        (TenderState.PROPOSED, TenderAction.INVITE),
        (TenderState.PROPOSED, TenderAction.FILL),
        (TenderState.REFUSED, TenderAction.APPROVE),
        (TenderState.APPROVED, TenderAction.ACCEPT_INVITATION),
        (TenderState.TENDER, TenderAction.APPROVE),
        (TenderState.FILLED, TenderAction.WITHDRAW),
        (TenderState.WITHDRAWN, TenderAction.RESUBMIT),
    ]
    for state, action in cases:
        with pytest.raises(ValueError):
            next_state(state, action)


def test_a_finished_proposal_is_not_open():
    """Filled and withdrawn proposals no longer hold the unit; every other state does."""
    assert TenderState.FILLED not in OPEN_STATES and TenderState.WITHDRAWN not in OPEN_STATES
    assert OPEN_STATES == set(TenderState) - {TenderState.FILLED, TenderState.WITHDRAWN}


def test_only_a_refusal_needs_a_comment():
    """The board tells the coordinator what is missing; the other steps need no comment."""
    assert needs_comment(TenderAction.REFUSE)
    for action in set(TenderAction) - {TenderAction.REFUSE}:
        assert not needs_comment(action)
