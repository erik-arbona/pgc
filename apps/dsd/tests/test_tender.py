"""Tests for the tender proposals: propose, decide, invite, fill (block 5, entrega 1).

Implements: docs/especificacao/05_dsd_regras.md – tender proposals; D17, D46, D86 (cell state),
D97 (the board decides without a cell), D105.
"""

# The fixtures come from other test modules; F811 flags every test that uses them.
# ruff: noqa: F811

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.models import AuditEntry
from apps.dsd.models import TenderEvent, TenderProposal
from apps.dsd.services import assign_teacher, change_state
from apps.dsd.tender_rules import TenderAction, TenderState
from apps.dsd.tenders import (
    decide_tender,
    fill_tender,
    propose_tender,
    resubmit_tender,
    withdraw_tender,
)
from apps.dsd.tests.test_assignment import make_teacher, unit_of, world  # noqa: F401
from apps.dsd.tests.test_below_minimum import board, open_cell  # noqa: F401
from apps.staff.models import Category, Teacher

pytestmark = pytest.mark.django_db

KIND = TenderProposal.ReasonKind.NO_PROFILE


def collaborator(coordination, identifier, active=True):
    """A habitual collaborator of a coordination."""
    return Teacher.objects.create(
        identifier=identifier,
        name=f"Colaborador {identifier}",
        coordination=coordination,
        category=Category.objects.get(name="Mestre"),
        teacher_type=Teacher.Type.HABITUAL_COLLABORATOR,
        is_active=active,
    )


def propose(world, unit=None, user=None, suggested=None, justification="Ninguém com o perfil."):
    """The coordinator proposes a unit (theory of turma A by default)."""
    return propose_tender(
        user or world["coordinator"],
        unit or unit_of(world, "A", "T"),
        KIND,
        justification,
        suggested,
    )


def decide(world, proposal, action, comment="", teacher=None, user=None):
    """The board decides on a proposal, with the version it last saw."""
    proposal.refresh_from_db()
    return decide_tender(user or world["ce"], proposal, action, comment, teacher, proposal.version)


def states(proposal):
    """The (from, to) pairs of the history of a proposal, in order."""
    return [(e.from_state, e.to_state) for e in proposal.events.order_by("pk")]


# --- proposing ---------------------------------------------------------------------------------


def test_the_coordinator_proposes_a_unit_without_a_teacher(board):
    """The proposal waits for the board and the history records it."""
    open_cell(board)
    proposal = propose(board)
    assert proposal.state == TenderState.PROPOSED
    assert proposal.unit == unit_of(board, "A", "T")
    assert states(proposal) == [("", TenderState.PROPOSED)]
    assert AuditEntry.objects.filter(entity="dsd.tenderproposal").exists()


def test_the_justification_and_a_valid_kind_are_required(board):
    """No blank justification (D17), no unknown kind."""
    open_cell(board)
    with pytest.raises(ValidationError):
        propose(board, justification="   ")
    with pytest.raises(ValidationError):
        propose_tender(board["coordinator"], unit_of(board, "A", "T"), "nonsense", "x", None)
    assert TenderProposal.objects.count() == 0


def test_a_unit_that_has_a_teacher_cannot_be_proposed(board):
    """There is nothing to look for."""
    open_cell(board)
    assign_teacher(board["coordinator"], unit_of(board, "A", "T"), board["mine"])
    with pytest.raises(ValidationError):
        propose(board)


def test_a_unit_takes_one_open_proposal_at_a_time(board):
    """The second one is refused; after the first is withdrawn a new one is fine."""
    open_cell(board)
    first = propose(board)
    with pytest.raises(ValidationError):
        propose(board)
    first.refresh_from_db()
    withdraw_tender(board["coordinator"], first, "Engano", first.version)
    assert propose(board).state == TenderState.PROPOSED


def test_the_suggested_collaborator_must_be_an_active_collaborator_of_the_coordination(board):
    """D46 suggests a collaborator, and D08 limits the coordinator to their own teachers."""
    open_cell(board)
    good = collaborator(board["coordination"], "C1")
    for bad in (
        board["mine"],  # full-time
        collaborator(board["foreign"].coordination, "C2"),  # another coordination
        collaborator(board["coordination"], "C3", active=False),
    ):
        with pytest.raises(ValidationError):
            propose(board, suggested=bad)
    assert propose(board, suggested=good).suggested_teacher == good


def test_scope_profile_and_cell_rules_apply_to_the_proposal(board):
    """Another coordination, a teacher account, the board; not opened; closed."""
    for user in (board["other_coordinator"], board["teacher_user"], board["ce"]):
        with pytest.raises(PermissionDenied):
            propose(board, user=user)
    with pytest.raises(ValidationError):  # the cell is not opened for the coordinator
        propose(board)
    open_cell(board)
    change_state(
        board["manager"], "close", [board["semester"]], [board["coordination"]], reason="fim"
    )
    with pytest.raises(ValidationError):
        propose(board, user=board["manager"])


# --- withdrawing -------------------------------------------------------------------------------


def test_the_coordinator_withdraws_with_a_reason_and_the_current_version(board):
    """A reason (D40) and the version the user saw (D54)."""
    open_cell(board)
    proposal = propose(board)
    with pytest.raises(ValidationError):
        withdraw_tender(board["coordinator"], proposal, " ", proposal.version)
    with pytest.raises(ValidationError):
        withdraw_tender(board["coordinator"], proposal, "x", proposal.version + 5)
    withdraw_tender(board["coordinator"], proposal, "Já encontrei", proposal.version)
    proposal.refresh_from_db()
    assert proposal.state == TenderState.WITHDRAWN


def test_a_proposal_cannot_be_withdrawn_once_the_invitation_went_out(board):
    """From then on the board owns the case."""
    open_cell(board)
    proposal = propose(board)
    decide(board, proposal, TenderAction.APPROVE)
    decide(board, proposal, TenderAction.INVITE, teacher=collaborator(board["coordination"], "C1"))
    proposal.refresh_from_db()
    with pytest.raises(ValidationError):
        withdraw_tender(board["coordinator"], proposal, "x", proposal.version)


# --- the board decides -------------------------------------------------------------------------


def test_the_board_approves_a_proposal(board):
    """Approved: the next step is an invitation or the tender."""
    open_cell(board)
    proposal = propose(board)
    assert decide(board, proposal, TenderAction.APPROVE).state == TenderState.APPROVED


def test_a_refusal_needs_a_comment_and_goes_back_to_the_coordinator(board):
    """The coordinator treats it again with a better justification (05)."""
    open_cell(board)
    proposal = propose(board)
    with pytest.raises(ValidationError):
        decide(board, proposal, TenderAction.REFUSE, comment=" ")
    refused = decide(board, proposal, TenderAction.REFUSE, comment="Falta justificar")
    assert refused.state == TenderState.REFUSED and refused.board_comment == "Falta justificar"
    resubmit_tender(
        board["coordinator"], refused, KIND, "Agora com detalhe.", None, refused.version
    )
    refused.refresh_from_db()
    assert refused.state == TenderState.PROPOSED
    assert refused.justification == "Agora com detalhe."


def test_only_a_refused_proposal_is_resubmitted_and_with_a_new_justification(board):
    """A proposal waiting for the board is not resubmitted; a blank justification is refused."""
    open_cell(board)
    proposal = propose(board)
    with pytest.raises(ValidationError):
        resubmit_tender(board["coordinator"], proposal, KIND, "x", None, proposal.version)
    refused = decide(board, proposal, TenderAction.REFUSE, comment="Falta")
    with pytest.raises(ValidationError):
        resubmit_tender(board["coordinator"], refused, KIND, "  ", None, refused.version)


def test_only_the_board_of_the_faculty_decides(board):
    """Coordinator, manager, teacher account and another Faculty's board are refused."""
    open_cell(board)
    proposal = propose(board)
    for user in (
        board["coordinator"],
        board["manager"],
        board["teacher_user"],
        board["other_ce"],
    ):
        with pytest.raises(PermissionDenied):
            decide(board, proposal, TenderAction.APPROVE, user=user)
    proposal.refresh_from_db()
    assert proposal.state == TenderState.PROPOSED


def test_the_board_decides_even_when_the_cell_is_closed(board):
    """Deciding is not writing the distribution (D97)."""
    open_cell(board)
    proposal = propose(board)
    change_state(
        board["manager"], "close", [board["semester"]], [board["coordination"]], reason="fim"
    )
    assert decide(board, proposal, TenderAction.APPROVE).state == TenderState.APPROVED


def test_a_decision_on_an_old_version_is_stale(board):
    """The coordinator changed the proposal while the board was reading it (D54)."""
    open_cell(board)
    proposal = propose(board)
    seen = proposal.version
    withdraw_tender(board["coordinator"], proposal, "Engano", proposal.version)
    with pytest.raises(ValidationError):
        decide_tender(board["ce"], proposal, TenderAction.APPROVE, "", None, seen)


def test_an_action_out_of_order_is_refused(board):
    """Inviting needs an approval first."""
    open_cell(board)
    proposal = propose(board)
    with pytest.raises(ValidationError):
        decide(
            board, proposal, TenderAction.INVITE, teacher=collaborator(board["coordination"], "C1")
        )


# --- invitation and tender ---------------------------------------------------------------------


def approved(board, **kwargs):
    """A proposal the board approved."""
    open_cell(board)
    proposal = propose(board, **kwargs)
    return decide(board, proposal, TenderAction.APPROVE)


def test_the_board_invites_a_collaborator_of_the_coordination(board):
    """The suggested one or another; full-time, foreign and inactive teachers are refused."""
    proposal = approved(board)
    for bad in (
        board["mine"],
        collaborator(board["foreign"].coordination, "C2"),
        collaborator(board["coordination"], "C3", active=False),
        None,
    ):
        with pytest.raises(ValidationError):
            decide(board, proposal, TenderAction.INVITE, teacher=bad)
    invited = collaborator(board["coordination"], "C1")
    done = decide(board, proposal, TenderAction.INVITE, teacher=invited)
    assert done.state == TenderState.INVITED and done.invited_teacher == invited


def test_a_declined_invitation_sends_the_unit_to_tender(board):
    """If the teacher or the board refuses, the subject goes to tender (D46)."""
    proposal = approved(board)
    decide(board, proposal, TenderAction.INVITE, teacher=collaborator(board["coordination"], "C1"))
    assert decide(board, proposal, TenderAction.DECLINE_INVITATION).state == TenderState.TENDER


def test_the_board_can_send_an_approved_proposal_straight_to_tender(board):
    """Without inviting anybody."""
    proposal = approved(board)
    assert decide(board, proposal, TenderAction.SEND_TO_TENDER).state == TenderState.TENDER


# --- giving the unit its teacher ---------------------------------------------------------------


def test_the_coordinator_assigns_the_collaborator_who_accepted_and_the_proposal_is_filled(board):
    """The normal assignment flow finishes the case."""
    proposal = approved(board)
    invited = collaborator(board["coordination"], "C1")
    decide(board, proposal, TenderAction.INVITE, teacher=invited)
    decide(board, proposal, TenderAction.ACCEPT_INVITATION)
    unit = unit_of(board, "A", "T")
    assign_teacher(board["coordinator"], unit, invited)
    proposal.refresh_from_db()
    unit.refresh_from_db()
    assert unit.teacher == invited and proposal.state == TenderState.FILLED


def test_a_unit_with_an_open_proposal_takes_no_other_teacher(board):
    """Only the accepted collaborator, or the winner of the tender, may be given the unit."""
    open_cell(board)
    proposal = propose(board)
    unit = unit_of(board, "A", "T")
    with pytest.raises(ValidationError):
        assign_teacher(board["coordinator"], unit, board["mine"])  # proposed
    decide(board, proposal, TenderAction.APPROVE)
    invited = collaborator(board["coordination"], "C1")
    decide(board, proposal, TenderAction.INVITE, teacher=invited)
    decide(board, proposal, TenderAction.ACCEPT_INVITATION)
    with pytest.raises(ValidationError):
        assign_teacher(board["coordinator"], unit, board["mine"])  # not the accepted one
    unit.refresh_from_db()
    assert unit.teacher is None


def test_after_the_proposal_is_withdrawn_the_unit_takes_a_teacher_again(board):
    """The normal flow is back."""
    open_cell(board)
    proposal = propose(board)
    withdraw_tender(board["coordinator"], proposal, "Engano", proposal.version)
    unit = unit_of(board, "A", "T")
    assign_teacher(board["coordinator"], unit, board["mine"])
    unit.refresh_from_db()
    assert unit.teacher == board["mine"]


def test_the_manager_registers_the_teacher_obtained_by_tender(board):
    """Only the manager fills a unit in tender, with a teacher of the coordination."""
    proposal = approved(board)
    decide(board, proposal, TenderAction.SEND_TO_TENDER)
    proposal.refresh_from_db()
    for user in (board["coordinator"], board["ce"], board["teacher_user"]):
        with pytest.raises(PermissionDenied):
            fill_tender(user, proposal, board["mine"], proposal.version)
    for bad in (board["foreign"], board["inactive"]):
        with pytest.raises((ValidationError, PermissionDenied)):
            fill_tender(board["manager"], proposal, bad, proposal.version)
    fill_tender(board["manager"], proposal, board["mine"], proposal.version)
    proposal.refresh_from_db()
    unit = unit_of(board, "A", "T")
    assert unit.teacher == board["mine"] and proposal.state == TenderState.FILLED


def test_only_a_unit_in_tender_is_filled_by_the_manager(board):
    """A proposal still with the board is not filled behind its back."""
    proposal = approved(board)
    with pytest.raises(ValidationError):
        fill_tender(board["manager"], proposal, board["mine"], proposal.version)


def test_the_history_records_every_step(board):
    """From the proposal to the filled unit, with who did it."""
    proposal = approved(board)
    decide(board, proposal, TenderAction.SEND_TO_TENDER)
    proposal.refresh_from_db()
    fill_tender(board["manager"], proposal, board["mine"], proposal.version)
    assert states(proposal) == [
        ("", TenderState.PROPOSED),
        (TenderState.PROPOSED, TenderState.APPROVED),
        (TenderState.APPROVED, TenderState.TENDER),
        (TenderState.TENDER, TenderState.FILLED),
    ]
    assert TenderEvent.objects.filter(proposal=proposal, actor=board["ce"]).count() == 2


# --- an open proposal holds its unit ------------------------------------------------------------


def test_a_unit_with_an_open_proposal_cannot_be_divided_into_groups(board):
    """Dividing the turma would delete the unit and its case: withdraw the proposal first."""
    from apps.dsd.services import set_group_count

    open_cell(board)
    proposal = propose(board)
    with pytest.raises(ValidationError):
        set_group_count(board["coordinator"], board["links"]["A"], board["T"], 2)
    assert unit_of(board, "A", "T").tender_proposals.count() == 1
    withdraw_tender(board["coordinator"], proposal, "Engano", proposal.version)
    set_group_count(board["coordinator"], board["links"]["A"], board["T"], 2)


def test_a_unit_with_an_open_proposal_cannot_be_merged(board):
    """The merge would delete one of the units, with its case in it."""
    from apps.dsd.services import merge_units

    open_cell(board)
    proposal = propose(board)
    units = [unit_of(board, "A", "T"), unit_of(board, "B", "T")]
    with pytest.raises(ValidationError):
        merge_units(board["coordinator"], units, 80)
    withdraw_tender(board["coordinator"], proposal, "Engano", proposal.version)
    merge_units(board["coordinator"], units, 80)


# --- review of the first part ---------------------------------------------------------------------


def test_the_board_cancels_a_case_that_cannot_go_on_and_the_unit_is_free_again(board):
    """The accepted collaborator was deactivated: the case would hold the unit forever."""
    open_cell(board)
    proposal = propose(board)
    decide(board, proposal, TenderAction.APPROVE)
    invited = collaborator(board["coordination"], "C1")
    decide(board, proposal, TenderAction.INVITE, teacher=invited)
    decide(board, proposal, TenderAction.ACCEPT_INVITATION)
    Teacher.objects.filter(pk=invited.pk).update(is_active=False)
    invited.refresh_from_db()  # a view always loads the teacher afresh
    unit = unit_of(board, "A", "T")
    with pytest.raises(ValidationError):
        assign_teacher(board["coordinator"], unit, invited)
    with pytest.raises(ValidationError):
        decide(board, proposal, TenderAction.CANCEL, comment=" ")
    assert decide(board, proposal, TenderAction.CANCEL, comment="Saiu").state == (
        TenderState.WITHDRAWN
    )
    assign_teacher(board["coordinator"], unit, board["mine"])


def test_the_board_cancels_a_proposal_in_tender_and_only_the_board_does(board):
    """A tender nobody fills can be closed; the coordinator cannot do it."""
    proposal = approved(board)
    decide(board, proposal, TenderAction.SEND_TO_TENDER)
    for user in (board["coordinator"], board["manager"], board["other_ce"]):
        with pytest.raises(PermissionDenied):
            decide(board, proposal, TenderAction.CANCEL, comment="x", user=user)
    assert decide(board, proposal, TenderAction.CANCEL, comment="Desistência").state == (
        TenderState.WITHDRAWN
    )


def test_a_merged_unit_with_an_open_proposal_cannot_be_separated(board):
    """Separating changes the audience the board approved."""
    from apps.dsd.services import merge_units, separate_member

    open_cell(board)
    merged = merge_units(
        board["coordinator"], [unit_of(board, "A", "T"), unit_of(board, "B", "T")], 80
    )
    proposal = propose(board, unit=merged)
    member = merged.members.first()
    with pytest.raises(ValidationError):
        separate_member(board["coordinator"], merged, member, "x")
    withdraw_tender(board["coordinator"], proposal, "Engano", proposal.version)
    separate_member(board["coordinator"], merged, member, "x")


def test_a_refused_proposal_of_a_unit_that_became_obsolete_is_not_resubmitted(board):
    """It could never be filled: the unit is no longer asked for."""
    from apps.academic.models import SubjectClassLoad

    open_cell(board)
    proposal = propose(board)
    refused = decide(board, proposal, TenderAction.REFUSE, comment="Falta")
    SubjectClassLoad.objects.filter(class_type=board["T"]).delete()
    with pytest.raises(ValidationError):
        resubmit_tender(board["coordinator"], refused, KIND, "Nova", None, refused.version)


def test_a_declined_invitation_forgets_the_invited_and_a_resubmission_forgets_the_comment(board):
    """Stale data does not stay on the row (the history keeps it)."""
    proposal = approved(board)
    decide(board, proposal, TenderAction.INVITE, teacher=collaborator(board["coordination"], "C1"))
    declined = decide(board, proposal, TenderAction.DECLINE_INVITATION)
    assert declined.invited_teacher is None
    other = TenderProposal.objects.get(pk=propose_other(board).pk)
    refused = decide(board, other, TenderAction.REFUSE, comment="Falta")
    assert refused.board_comment == "Falta"
    resubmit_tender(board["coordinator"], refused, KIND, "Nova", None, refused.version)
    refused.refresh_from_db()
    assert refused.board_comment == ""


def propose_other(board):
    """A proposal on the practice unit of turma A."""
    return propose(board, unit=unit_of(board, "A", "P"))
