"""Tests for the room alerts and the warning before closing a semester (T4.5).

Implements: docs/especificacao/05_dsd_regras.md – the system warns before the PGC manager closes
the semester of a coordination; docs/backlog_fase2.md T4.5; D64 (quantities, never a room), D86,
D102.
"""

# The fixtures come from other test modules; F811 flags every test that uses them.
# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.academic.models import ClassType, Coordination, SubjectClassLoad
from apps.dsd.coordination_overview import attention_text, coordination_overview
from apps.dsd.models import CoordinationSemester
from apps.dsd.overview import AttentionItem, AttentionKind, attention_items
from apps.dsd.services import change_state, set_room_request
from apps.dsd.tests.test_assignment import unit_of, world  # noqa: F401
from apps.dsd.tests.test_below_minimum import board, open_cell  # noqa: F401

pytestmark = pytest.mark.django_db

D = Decimal


# --- the pure rule -----------------------------------------------------------------------------


def test_units_without_a_room_request_are_an_item_with_their_count():
    """Three units that ask for no room."""
    [item] = attention_items(0, 0, [], room_missing=3)
    assert item == AttentionItem(AttentionKind.ROOM_MISSING, 3)


def test_requests_no_room_can_serve_are_an_item_with_their_count():
    """Two units whose request no room of the campus meets."""
    [item] = attention_items(0, 0, [], room_unfit=2)
    assert item == AttentionItem(AttentionKind.ROOM_UNFIT, 2)


def test_no_room_alerts_when_there_is_nothing_to_say():
    """Zero is not an item."""
    assert attention_items(0, 0, [], room_missing=0, room_unfit=0) == []


def test_the_room_items_come_after_the_units_and_before_the_teachers_items():
    """Units, rooms, then the teachers' items, whatever the input."""
    kinds = [item.kind for item in attention_items(1, 1, [], room_missing=1, room_unfit=1)]
    assert kinds == [
        AttentionKind.UNASSIGNED_UNITS,
        AttentionKind.STALE_UNITS,
        AttentionKind.ROOM_MISSING,
        AttentionKind.ROOM_UNFIT,
    ]


# --- what the overview counts ------------------------------------------------------------------


def overview(world, number=1):
    """The overview of the coordination for a semester."""
    return coordination_overview(world["semester"].dsd, number, world["coordination"])


def test_every_unit_without_a_request_counts_as_missing_a_room(board):
    """Four units and no request yet."""
    assert overview(board).room_missing == 4


def test_a_request_takes_the_unit_off_the_missing_ones(board):
    """One unit asks for 30 places."""
    open_cell(board)
    set_room_request(board["coordinator"], unit_of(board, "A", "T"), 30, None)
    assert overview(board).room_missing == 3


def test_a_request_that_no_room_meets_is_counted_apart(board):
    """The only room of the demo has 80 places: 500 cannot be met (D64, quantities only)."""
    open_cell(board)
    set_room_request(board["coordinator"], unit_of(board, "A", "T"), 500, None)
    set_room_request(board["coordinator"], unit_of(board, "B", "T"), 30, None)
    result = overview(board)
    assert result.room_unfit == 1
    assert result.room_missing == 2


def test_obsolete_units_are_not_counted_for_rooms(board):
    """The plan drops practice: only the two T units still count."""
    SubjectClassLoad.objects.filter(class_type=ClassType.objects.get(code="P")).delete()
    assert overview(board).room_missing == 2


def test_the_text_of_the_room_items_is_in_words():
    """The sentences the screens show."""
    assert "3" in attention_text(AttentionItem(AttentionKind.ROOM_MISSING, 3))
    assert "sala" in attention_text(AttentionItem(AttentionKind.ROOM_UNFIT, 2))


def test_the_overview_page_lists_the_room_items(board, client):
    """The coordinator sees them too, with the rest of what needs attention."""
    client.force_login(board["coordinator"])
    page = reverse(
        "dsd:coordination_overview", args=[board["semester"].dsd.pk, board["coordination"].pk]
    )
    assert "sem pedido de sala" in client.get(page).content.decode()


# --- the warning before closing ----------------------------------------------------------------


def state_url(world):
    """The page that opens, closes and reopens semesters."""
    return reverse("dsd:dsd_state", args=[world["semester"].dsd.pk])


def close(client, world, coordination, confirm=False, semester="1"):
    """Ask to close a semester for a coordination."""
    data = {
        "action": "close",
        "semester": semester,
        "coordination": coordination.pk,
        "reason": "Fim do prazo",
    }
    if confirm:
        data["confirm_close"] = "1"
    return client.post(state_url(world), data)


def status_of(world, coordination):
    """The state of the first semester of a coordination."""
    cell = CoordinationSemester.objects.filter(
        dsd_semester=world["semester"], coordination=coordination
    ).first()
    return cell.status if cell else None


def test_closing_with_pending_things_asks_for_confirmation_and_closes_nothing(board, client):
    """The page lists what is pending; the semester is still open."""
    open_cell(board)
    client.force_login(board["manager"])
    response = close(client, board, board["coordination"])
    assert response.status_code == 200
    html = response.content.decode()
    assert "Fechar mesmo assim" in html
    assert "por atribuir" in html
    assert "sem pedido de sala" in html
    assert status_of(board, board["coordination"]) == CoordinationSemester.Status.OPEN


def test_confirming_closes_it_even_with_pending_things(board, client):
    """The warning does not block: the manager decides (05)."""
    open_cell(board)
    client.force_login(board["manager"])
    response = close(client, board, board["coordination"], confirm=True)
    assert response.status_code == 302
    assert status_of(board, board["coordination"]) == CoordinationSemester.Status.CLOSED


def test_closing_a_coordination_with_nothing_pending_needs_no_confirmation(board, client):
    """As before: no warnings, it closes straight away."""
    empty = Coordination.objects.create(faculty=board["coordination"].faculty, name="Vazia")
    change_state(board["manager"], "open", [board["semester"]], [empty])
    client.force_login(board["manager"])
    response = close(client, board, empty)
    assert response.status_code == 302
    assert status_of(board, empty) == CoordinationSemester.Status.CLOSED


def test_only_the_open_cells_are_warned_about(board, client):
    """A cell that was never opened has nothing to close, so there is nothing to warn about."""
    client.force_login(board["manager"])
    response = close(client, board, board["coordination"])
    assert "Fechar mesmo assim" not in response.content.decode()


def test_opening_and_reopening_are_not_warned_about(board, client):
    """Only closing has a warning."""
    client.force_login(board["manager"])
    response = client.post(
        state_url(board),
        {"action": "open", "semester": "1", "coordination": board["coordination"].pk},
    )
    assert response.status_code == 302
    assert status_of(board, board["coordination"]) == CoordinationSemester.Status.OPEN


def test_the_warning_names_the_coordination_and_the_semester(board, client):
    """So the manager knows what each list is about."""
    open_cell(board)
    client.force_login(board["manager"])
    html = close(client, board, board["coordination"]).content.decode()
    assert board["coordination"].name in html
    assert "1.º semestre" in html


def test_closing_for_all_the_coordinations_lists_each_one_with_something_pending(board, client):
    """Several cells in one request: each cell with pending things gets its own list."""
    open_cell(board)
    change_state(board["manager"], "open", [board["semester"]], [board["foreign"].coordination])
    client.force_login(board["manager"])
    response = client.post(
        state_url(board),
        {"action": "close", "semester": "1", "coordination": "", "reason": "Fim do prazo"},
    )
    assert response.status_code == 200
    assert board["coordination"].name in response.content.decode()
    assert status_of(board, board["coordination"]) == CoordinationSemester.Status.OPEN


def test_the_confirmation_is_only_for_who_may_change_states(board, client):
    """The coordinator cannot reach this screen at all (D86)."""
    client.force_login(board["coordinator"])
    assert close(client, board, board["coordination"], confirm=True).status_code == 403


def test_a_cell_that_is_already_closed_is_not_warned_about_again(board, client):
    """Closing twice: the second time there is nothing left to close, so no warning."""
    open_cell(board)
    client.force_login(board["manager"])
    assert close(client, board, board["coordination"], confirm=True).status_code == 302
    second = close(client, board, board["coordination"])
    assert second.status_code == 302
    assert "Fechar mesmo assim" not in second.content.decode()
