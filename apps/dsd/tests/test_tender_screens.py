"""Tests for the screens of the tender proposals: propose, read and act (block 5, part 2a).

Implements: docs/especificacao/05_dsd_regras.md – tender proposals; D17, D46, D50 (forms that work
without JavaScript), D86, D97, D105, D106.
"""

# The fixtures come from other test modules; F811 flags every test that uses them.
# ruff: noqa: F811

import pytest
from django.urls import reverse

from apps.dsd.models import TenderProposal
from apps.dsd.services import assign_teacher
from apps.dsd.tender_rules import TenderAction, TenderState
from apps.dsd.tenders import decide_tender
from apps.dsd.tests.test_assignment import unit_of, world  # noqa: F401
from apps.dsd.tests.test_below_minimum import board, open_cell  # noqa: F401
from apps.dsd.tests.test_tender import approved, collaborator, decide, propose

pytestmark = pytest.mark.django_db


def offering_url(world):
    """The page of the offering."""
    return reverse("dsd:offering_detail", args=[world["offering"].pk])


def propose_url(world, unit=None):
    """The page that proposes a unit to tender."""
    unit = unit or unit_of(world, "A", "T")
    return reverse("dsd:tender_propose", args=[world["offering"].pk, unit.pk])


def detail_url(proposal):
    """The page of a proposal."""
    return reverse("dsd:tender_detail", args=[proposal.pk])


def action_url(proposal, action):
    """The page that does an action on a proposal."""
    return reverse("dsd:tender_action", args=[proposal.pk, action])


def refreshed(proposal):
    """The proposal as stored."""
    proposal.refresh_from_db()
    return proposal


# --- proposing from the offering page ----------------------------------------------------------


def test_a_unit_without_a_teacher_offers_to_propose_it_to_tender(board, client):
    """The link shows to who may write the cell, on units nobody has been given."""
    open_cell(board)
    client.force_login(board["coordinator"])
    html = client.get(offering_url(board)).content.decode()
    assert propose_url(board) in html


def test_the_link_does_not_show_when_the_cell_is_not_open_or_the_unit_has_a_teacher(board, client):
    """Not opened for the coordinator; a unit with a teacher has nothing to propose."""
    client.force_login(board["coordinator"])
    assert propose_url(board) not in client.get(offering_url(board)).content.decode()
    open_cell(board)
    assign_teacher(board["coordinator"], unit_of(board, "A", "T"), board["mine"])
    assert propose_url(board) not in client.get(offering_url(board)).content.decode()


def test_the_coordinator_proposes_a_unit_from_the_form(board, client):
    """POST creates the proposal and goes to its page."""
    open_cell(board)
    client.force_login(board["coordinator"])
    response = client.post(
        propose_url(board),
        {"reason_kind": "no_profile", "justification": "Ninguém com o perfil."},
    )
    proposal = TenderProposal.objects.get()
    assert response.status_code == 302 and response.url == detail_url(proposal)
    assert proposal.state == TenderState.PROPOSED


def test_the_form_shows_the_error_and_creates_nothing(board, client):
    """A blank justification stays on the form."""
    open_cell(board)
    client.force_login(board["coordinator"])
    response = client.post(propose_url(board), {"reason_kind": "no_profile", "justification": " "})
    assert response.status_code == 200
    assert TenderProposal.objects.count() == 0


def test_the_form_only_offers_the_collaborators_of_the_coordination(board, client):
    """Active habitual collaborators of the coordination: not full-time, not foreign."""
    good = collaborator(board["coordination"], "C1")
    collaborator(board["foreign"].coordination, "C2")
    open_cell(board)
    client.force_login(board["coordinator"])
    html = client.get(propose_url(board)).content.decode()
    assert good.name in html
    assert "Colaborador C2" not in html and board["mine"].name not in html


def test_the_row_shows_the_state_of_the_proposal_instead_of_the_link(board, client):
    """Once proposed, the unit says where the case is."""
    open_cell(board)
    proposal = propose(board)
    client.force_login(board["coordinator"])
    html = client.get(offering_url(board)).content.decode()
    assert detail_url(proposal) in html
    assert propose_url(board) not in html
    assert "à espera do Conselho" in html


def test_only_users_who_cover_the_coordination_propose(board, client):
    """Another coordination and teacher accounts get 403 (D69)."""
    open_cell(board)
    for user in (board["other_coordinator"], board["teacher_user"], board["ce"]):
        client.force_login(user)
        assert client.get(propose_url(board)).status_code == 403
    assert client.get(propose_url(board)).status_code == 403
    client.logout()
    assert client.get(propose_url(board)).status_code == 302


# --- reading a proposal ------------------------------------------------------------------------


def test_the_page_of_a_proposal_shows_the_case_and_its_history(board, client):
    """Justification, state and the steps so far, to who may read it."""
    open_cell(board)
    proposal = propose(board, justification="Ninguém <b>com</b> o perfil.")
    client.force_login(board["coordinator"])
    html = client.get(detail_url(proposal)).content.decode()
    assert "Ninguém &lt;b&gt;com&lt;/b&gt; o perfil." in html  # escaped
    assert "à espera do Conselho" in html
    assert "Histórico" in html


def test_who_may_read_a_proposal(board, client):
    """The coordinator, the manager and the board of the Faculty; others are refused."""
    open_cell(board)
    proposal = propose(board)
    for user in (board["coordinator"], board["manager"], board["ce"]):
        client.force_login(user)
        assert client.get(detail_url(proposal)).status_code == 200
    for user in (board["other_coordinator"], board["other_ce"], board["teacher_user"]):
        client.force_login(user)
        assert client.get(detail_url(proposal)).status_code == 403
    client.logout()
    assert client.get(detail_url(proposal)).status_code == 302


def available(client, user, proposal):
    """The actions the page offers a user, as the URLs it links."""
    client.force_login(user)
    html = client.get(detail_url(proposal)).content.decode()
    return {action.value for action in TenderAction if action_url(proposal, action.value) in html}


def test_each_role_sees_only_the_actions_it_may_do_in_each_state(board, client):
    """The buttons follow the role and the state (the server checks again)."""
    open_cell(board)
    proposal = propose(board)
    assert available(client, board["coordinator"], proposal) == {"withdraw"}
    assert available(client, board["ce"], proposal) == {"approve", "refuse", "cancel"}
    # The manager may act for the coordinator (D86), but never as the board.
    assert available(client, board["manager"], proposal) == {"withdraw"}
    decide(board, proposal, TenderAction.APPROVE)
    assert available(client, board["ce"], proposal) == {"invite", "send_to_tender", "cancel"}
    assert available(client, board["coordinator"], proposal) == {"withdraw"}
    decide(board, proposal, TenderAction.SEND_TO_TENDER)
    assert available(client, board["manager"], proposal) == {"fill"}
    assert available(client, board["ce"], proposal) == {"cancel"}
    assert available(client, board["coordinator"], proposal) == set()


def test_a_refused_proposal_offers_the_coordinator_to_treat_it_again(board, client):
    """Refused: resubmit or withdraw."""
    open_cell(board)
    proposal = propose(board)
    decide(board, proposal, TenderAction.REFUSE, comment="Falta justificar")
    assert available(client, board["coordinator"], proposal) == {"resubmit", "withdraw"}
    client.force_login(board["coordinator"])
    assert "Falta justificar" in client.get(detail_url(proposal)).content.decode()


def test_an_accepted_invitation_points_the_coordinator_to_the_assignment(board, client):
    """The coordinator assigns the collaborator with the normal flow."""
    proposal = approved(board)
    invited = collaborator(board["coordination"], "C1")
    decide(board, proposal, TenderAction.INVITE, teacher=invited)
    decide(board, proposal, TenderAction.ACCEPT_INVITATION)
    client.force_login(board["coordinator"])
    html = client.get(detail_url(proposal)).content.decode()
    assert reverse("dsd:offering_detail", args=[board["offering"].pk]) in html
    assert invited.name in html


# --- acting on a proposal ----------------------------------------------------------------------


def post(client, user, proposal, action, **data):
    """Do an action as a user, with the version of the proposal as stored."""
    client.force_login(user)
    proposal.refresh_from_db()
    data.setdefault("seen", proposal.version)
    return client.post(action_url(proposal, action), data)


def test_the_board_approves_and_refuses_from_the_screens(board, client):
    """Approve needs nothing; refuse needs a comment."""
    open_cell(board)
    refused = propose(board)
    assert post(client, board["ce"], refused, "refuse", comment=" ").status_code == 200
    assert refreshed(refused).state == TenderState.PROPOSED
    response = post(client, board["ce"], refused, "refuse", comment="Falta justificar")
    assert response.status_code == 302 and response.url == detail_url(refused)
    assert refreshed(refused).state == TenderState.REFUSED
    other = propose(board, unit=unit_of(board, "A", "P"))
    assert post(client, board["ce"], other, "approve").status_code == 302
    assert refreshed(other).state == TenderState.APPROVED


def test_the_board_invites_a_collaborator_and_records_the_answer(board, client):
    """Invite with a teacher, then accept."""
    proposal = approved(board)
    invited = collaborator(board["coordination"], "C1")
    assert post(client, board["ce"], proposal, "invite").status_code == 200  # no teacher chosen
    assert post(client, board["ce"], proposal, "invite", teacher=invited.pk).status_code == 302
    assert refreshed(proposal).state == TenderState.INVITED
    assert post(client, board["ce"], proposal, "accept_invitation").status_code == 302
    assert refreshed(proposal).state == TenderState.ACCEPTED


def test_the_board_sends_to_tender_and_the_manager_fills_it(board, client):
    """A tender nobody wins is filled by the manager with a teacher of the coordination."""
    proposal = approved(board)
    assert post(client, board["ce"], proposal, "send_to_tender").status_code == 302
    assert (
        post(client, board["manager"], proposal, "fill", teacher=board["foreign"].pk).status_code
        == 200
    )
    response = post(client, board["manager"], proposal, "fill", teacher=board["mine"].pk)
    assert response.status_code == 302
    assert refreshed(proposal).state == TenderState.FILLED
    unit = unit_of(board, "A", "T")
    unit.refresh_from_db()
    assert unit.teacher == board["mine"]


def test_the_coordinator_withdraws_with_a_reason_and_resubmits_a_refused_one(board, client):
    """Both from the screens, with the version the page carried."""
    open_cell(board)
    first = propose(board)
    assert post(client, board["coordinator"], first, "withdraw", reason=" ").status_code == 200
    assert post(client, board["coordinator"], first, "withdraw", reason="Engano").status_code == 302
    assert refreshed(first).state == TenderState.WITHDRAWN
    second = propose(board)
    decide(board, second, TenderAction.REFUSE, comment="Falta")
    response = post(
        client,
        board["coordinator"],
        second,
        "resubmit",
        reason_kind="no_profile",
        justification="Agora com detalhe.",
    )
    assert response.status_code == 302
    assert refreshed(second).state == TenderState.PROPOSED


def test_an_action_the_user_may_not_do_is_refused(board, client):
    """The server checks the role and the state, not only the buttons."""
    open_cell(board)
    proposal = propose(board)
    assert post(client, board["coordinator"], proposal, "approve").status_code == 403
    assert post(client, board["manager"], proposal, "approve").status_code == 403
    assert post(client, board["ce"], proposal, "withdraw").status_code == 403
    assert post(client, board["ce"], proposal, "invite").status_code == 404  # not approved yet
    assert post(client, board["ce"], proposal, "nonsense").status_code == 404
    assert refreshed(proposal).state == TenderState.PROPOSED


def test_the_board_of_another_faculty_cannot_act(board, client):
    """Scope by Faculty (D69)."""
    open_cell(board)
    proposal = propose(board)
    assert post(client, board["other_ce"], proposal, "approve").status_code == 403


def test_a_stale_version_or_a_forged_number_shows_an_error_not_a_server_error(board, client):
    """Someone else changed the case, or the form was forged."""
    open_cell(board)
    proposal = propose(board)
    assert (
        post(client, board["ce"], proposal, "approve", seen=proposal.version + 5).status_code == 200
    )
    assert post(client, board["ce"], proposal, "approve", seen="²").status_code == 200
    assert post(client, board["ce"], proposal, "approve", seen="").status_code == 200
    assert refreshed(proposal).state == TenderState.PROPOSED


def test_the_action_page_shows_the_form_of_the_action(board, client):
    """GET shows the form with the version, to who may do it."""
    open_cell(board)
    proposal = propose(board)
    client.force_login(board["ce"])
    response = client.get(action_url(proposal, "refuse"))
    assert response.status_code == 200
    assert 'name="seen"' in response.content.decode()
    client.force_login(board["coordinator"])
    assert client.get(action_url(proposal, "refuse")).status_code == 403


def test_the_decisions_leave_the_board_able_to_cancel_a_case_that_cannot_go_on(board, client):
    """Cancel needs a comment and works from the tender state."""
    proposal = approved(board)
    decide_tender(board["ce"], proposal, TenderAction.SEND_TO_TENDER, "", None, proposal.version)
    assert post(client, board["ce"], proposal, "cancel", comment=" ").status_code == 200
    assert post(client, board["ce"], proposal, "cancel", comment="Desistência").status_code == 302
    assert refreshed(proposal).state == TenderState.WITHDRAWN


def test_in_a_closed_cell_the_coordinator_loses_the_buttons_and_the_board_keeps_them(board, client):
    """The distribution is closed (D86), but the board still decides (D97)."""
    from apps.dsd.services import change_state

    open_cell(board)
    proposal = propose(board)
    change_state(
        board["manager"], "close", [board["semester"]], [board["coordination"]], reason="fim"
    )
    assert available(client, board["coordinator"], proposal) == set()
    assert available(client, board["ce"], proposal) == {"approve", "refuse", "cancel"}
    assert post(client, board["ce"], proposal, "approve").status_code == 302


# --- review of the screens ----------------------------------------------------------------------


def test_the_offering_row_links_to_a_proposal_only_for_who_can_read_it(board, client):
    """dsd.view is not scoped, dsd.tender.view is: a link that gives 403 is a defect (review)."""
    open_cell(board)
    proposal = propose(board)
    client.force_login(board["coordinator"])
    assert detail_url(proposal) in client.get(offering_url(board)).content.decode()
    # A coordinator of another coordination reads the offering but not the proposal.
    client.force_login(board["other_coordinator"])
    html = client.get(offering_url(board)).content.decode()
    assert detail_url(proposal) not in html
    assert "à espera do Conselho" in html  # the state is still shown, as text


def test_the_hint_to_assign_the_collaborator_follows_the_cell(board, client):
    """In a closed cell the coordinator cannot assign, so the page does not tell them to."""
    from apps.dsd.services import change_state

    proposal = approved(board)
    invited = collaborator(board["coordination"], "C1")
    decide(board, proposal, TenderAction.INVITE, teacher=invited)
    decide(board, proposal, TenderAction.ACCEPT_INVITATION)
    client.force_login(board["coordinator"])
    assert "O convite foi aceite" in client.get(detail_url(proposal)).content.decode()
    change_state(
        board["manager"], "close", [board["semester"]], [board["coordination"]], reason="fim"
    )
    assert "O convite foi aceite" not in client.get(detail_url(proposal)).content.decode()
