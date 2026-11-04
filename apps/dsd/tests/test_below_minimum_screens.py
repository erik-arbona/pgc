"""Tests for the screens of the reason below the minimum and its review (T5.5).

Implements: docs/backlog_fase2.md T5.5; D16, D97, Q14 (the refusal is shown in the application).
"""

# The ``world`` fixture comes from test_assignment; F811 flags every test that uses it.
# ruff: noqa: F811

import pytest
from django.urls import reverse

from apps.dsd.below_minimum import MinimumReasonState
from apps.dsd.models import BelowMinimumReason, BelowMinimumReview
from apps.dsd.services import change_state, review_minimum_reason, set_minimum_reason
from apps.dsd.tests.test_assignment import world  # noqa: F401
from apps.dsd.tests.test_below_minimum import board, open_cell  # noqa: F401

pytestmark = pytest.mark.django_db


def urls(world):
    """The URLs of the screens, for the teacher ``mine``."""
    dsd = world["semester"].dsd
    return {
        "register": reverse("dsd:minimum_reason", args=[dsd.pk, world["mine"].pk]),
        "list": reverse("dsd:minimum_review_list", args=[dsd.pk]),
        "sheet": reverse("dsd:teacher_sheet", args=[dsd.pk, world["mine"].pk]),
    }


def record(world, text="Licença parcial"):
    """A reason registered by the coordinator."""
    return set_minimum_reason(world["coordinator"], world["mine"], world["semester"].dsd, text)


def test_the_coordinator_registers_the_reason_from_the_screen(board, client):
    """POST stores it and goes back to the sheet."""
    open_cell(board)
    client.force_login(board["coordinator"])
    response = client.post(urls(board)["register"], {"text": "Licença parcial"})
    assert response.status_code == 302
    assert response.url == urls(board)["sheet"]
    assert BelowMinimumReason.objects.get().text == "Licença parcial"


def test_changing_the_reason_from_the_screen_needs_the_version(board, client):
    """Without the version the form is shown again and nothing changes."""
    open_cell(board)
    existing = record(board)
    client.force_login(board["coordinator"])
    assert client.post(urls(board)["register"], {"text": "Outro"}).status_code == 200
    assert BelowMinimumReason.objects.get().text == "Licença parcial"
    data = {"text": "Outro", "seen": existing.version}
    assert client.post(urls(board)["register"], data).status_code == 302
    assert BelowMinimumReason.objects.get().text == "Outro"


def test_the_register_screen_is_closed_to_the_board_and_other_users(board, client):
    """Scope and profile (D69)."""
    open_cell(board)
    for user in (board["other_coordinator"], board["teacher_user"], board["ce"]):
        client.force_login(user)
        assert client.get(urls(board)["register"]).status_code == 403


def test_the_board_sees_the_teachers_below_the_minimum_with_their_reasons(board, client):
    """The list has the teacher, the reason and the state."""
    open_cell(board)
    record(board)
    client.force_login(board["ce"])
    html = client.get(urls(board)["list"]).content.decode()
    assert board["mine"].name in html
    assert "Licença parcial" in html
    assert "por avaliar" in html


def test_the_list_is_closed_to_users_who_cannot_review(board, client):
    """The coordinator and a teacher account get 403; another Faculty sees nothing."""
    open_cell(board)
    record(board)
    for user in (board["coordinator"], board["teacher_user"]):
        client.force_login(user)
        assert client.get(urls(board)["list"]).status_code == 403
    client.force_login(board["other_ce"])
    response = client.get(urls(board)["list"])
    assert response.status_code == 403 or board["mine"].name not in response.content.decode()


def test_the_board_decides_from_the_screen(board, client):
    """Accept; refuse needs a comment; the state follows."""
    open_cell(board)
    existing = record(board)
    url = reverse("dsd:minimum_review", args=[existing.pk])
    client.force_login(board["ce"])
    bad = {"decision": "refused", "comment": "", "seen": existing.version}
    assert client.post(url, bad).status_code == 200
    assert BelowMinimumReview.objects.count() == 0
    good = {"decision": "refused", "comment": "Não justifica", "seen": existing.version}
    assert client.post(url, good).status_code == 302
    assert BelowMinimumReview.objects.get().decision == "refused"


def test_the_review_screen_is_closed_to_the_coordinator_and_other_faculties(board, client):
    """Only the board of the Faculty reviews (D69)."""
    open_cell(board)
    existing = record(board)
    url = reverse("dsd:minimum_review", args=[existing.pk])
    for user in (board["coordinator"], board["teacher_user"], board["other_ce"]):
        client.force_login(user)
        assert client.get(url).status_code == 403


def test_the_sheet_shows_the_state_and_the_refusal_to_the_coordinator(board, client):
    """Q14 = A: the refusal and its comment are shown in the application."""
    open_cell(board)
    client.force_login(board["coordinator"])
    assert "motivo em falta" in client.get(urls(board)["sheet"]).content.decode()
    existing = record(board)
    review_minimum_reason(board["ce"], existing, "refused", "Não justifica", existing.version)
    html = client.get(urls(board)["sheet"]).content.decode()
    assert "motivo recusado" in html
    assert "Não justifica" in html


def test_the_register_link_follows_the_cell(board, client):
    """Not opened: the coordinator sees no link; the manager does (D86)."""
    client.force_login(board["coordinator"])
    assert "/below-minimum/" not in client.get(urls(board)["sheet"]).content.decode()
    client.force_login(board["manager"])
    assert "/below-minimum/" in client.get(urls(board)["sheet"]).content.decode()


def test_the_state_text_appears_in_the_offering_rows(board):
    """The same text is used where the teacher is shown (not asserted here)."""
    from apps.dsd.load_facts import load_text, teacher_loads

    load = teacher_loads(board["semester"].dsd, [board["mine"]])[board["mine"].pk]
    assert load.minimum_reason == MinimumReasonState.MISSING
    assert "motivo em falta" in load_text(load)
    change_state(board["manager"], "open", [board["semester"]], [board["coordination"]])
