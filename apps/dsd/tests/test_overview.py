"""Tests for the overview of a coordination: the data and the screen (T6.1).

Implements: docs/especificacao/07_arquitetura.md – overview of the coordination; D20, D69
(scope by coordination), D98.
"""

# The fixtures come from other test modules; F811 flags every test that uses them.
# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.academic.models import ClassType, SubjectClassLoad
from apps.dsd.coordination_overview import coordination_overview
from apps.dsd.overview import AttentionKind
from apps.dsd.services import (
    assign_teacher,
    review_minimum_reason,
    set_minimum_reason,
)
from apps.dsd.tests.test_assignment import unit_of, world  # noqa: F401
from apps.dsd.tests.test_below_minimum import board, open_cell  # noqa: F401

pytestmark = pytest.mark.django_db

D = Decimal


def overview(world, number=1):
    """The overview of the coordination for a semester."""
    return coordination_overview(world["semester"].dsd, number, world["coordination"])


def item(result, kind):
    """The item of a kind, or None."""
    return next((i for i in result.items if i.kind == kind), None)


def url(world, number=None):
    """The URL of the overview screen."""
    base = reverse(
        "dsd:coordination_overview", args=[world["semester"].dsd.pk, world["coordination"].pk]
    )
    return base if number is None else f"{base}?semester={number}"


def test_every_unit_without_a_teacher_is_still_to_assign(board):
    """Two turmas, theory and practice: four units and nobody yet."""
    result = overview(board)
    assert result.unassigned_units == 4
    assert item(result, AttentionKind.UNASSIGNED_UNITS).count == 4


def test_assigning_a_teacher_takes_the_unit_off_the_pending_ones(board):
    """One of the four is given."""
    open_cell(board)
    assign_teacher(board["coordinator"], unit_of(board, "A", "T"), board["mine"])
    assert overview(board).unassigned_units == 3


def test_obsolete_units_are_counted_apart_and_not_as_to_assign(board):
    """The plan drops practice: the two P units are obsolete, not 'to assign'."""
    SubjectClassLoad.objects.filter(class_type=ClassType.objects.get(code="P")).delete()
    result = overview(board)
    assert result.stale_units == 2
    assert result.unassigned_units == 2


def test_the_teachers_of_the_coordination_appear_with_their_load_and_a_bar(board):
    """Active teachers only; the inactive one and the other coordination's are left out."""
    names = {row.teacher.identifier for row in overview(board).rows}
    assert names == {"T1", "T2"}
    row = next(r for r in overview(board).rows if r.teacher.identifier == "T1")
    assert row.bar.maximum_percent == D("100.0")
    assert row.bar.minimum_percent is not None
    assert row.status


def test_a_teacher_below_the_minimum_is_pending_until_the_reason_is_accepted(board):
    """Missing, then pending the board, then refused (back to the coordinator), then accepted."""
    open_cell(board)
    assert item(overview(board), AttentionKind.REASON_MISSING).count == 2
    reason = set_minimum_reason(
        board["coordinator"], board["mine"], board["semester"].dsd, "Licença"
    )
    assert item(overview(board), AttentionKind.REASON_PENDING).teacher_ids == (board["mine"].pk,)
    review_minimum_reason(board["ce"], reason, "refused", "Falta justificar", reason.version)
    assert item(overview(board), AttentionKind.REASON_REFUSED).teacher_ids == (board["mine"].pk,)
    review_minimum_reason(board["ce"], reason, "accepted", "", reason.version)
    result = overview(board)
    assert item(result, AttentionKind.REASON_REFUSED) is None
    assert item(result, AttentionKind.REASON_PENDING) is None


def test_the_overview_reads_a_fixed_number_of_queries_whatever_the_teachers(board):
    """More teachers do not mean more queries (no N+1)."""
    overview(board)  # warm caches that are not about the teachers
    with CaptureQueriesContext(connection) as before:
        overview(board)
    from apps.dsd.tests.test_assignment import make_teacher

    for index in range(5, 9):
        make_teacher(board["coordination"], f"T{index}")
    with CaptureQueriesContext(connection) as after:
        overview(board)
    assert len(after) == len(before)


def test_the_coordinator_sees_the_screen_with_the_pending_items_and_the_status_text(board, client):
    """The text of the state is on the page, not only a colour."""
    open_cell(board)
    client.force_login(board["coordinator"])
    response = client.get(url(board))
    assert response.status_code == 200
    html = response.content.decode()
    assert board["mine"].name in html
    assert "abaixo do mínimo" in html
    assert "por atribuir" in html


def test_the_bar_is_on_the_page_with_the_hours_and_the_range(board, client):
    """A real element with the values, readable without colour."""
    client.force_login(board["coordinator"])
    html = client.get(url(board)).content.decode()
    assert 'role="meter"' in html
    assert 'aria-valuemax="12' in html


def test_the_semester_can_be_chosen(board, client):
    """The second semester has its own units."""
    client.force_login(board["coordinator"])
    assert client.get(url(board, 2)).status_code == 200
    assert client.get(url(board, 3)).status_code == 404


def test_only_users_who_cover_the_coordination_see_it(board, client):
    """The coordinator, the manager and the board of the Faculty may; others get 403."""
    for user in (board["coordinator"], board["manager"], board["ce"]):
        client.force_login(user)
        assert client.get(url(board)).status_code == 200
    for user in (board["other_coordinator"], board["other_ce"], board["teacher_user"]):
        client.force_login(user)
        assert client.get(url(board)).status_code == 403


def test_the_screen_needs_a_session(board, client):
    """Anonymous users go to the login."""
    assert client.get(url(board)).status_code == 302


def test_the_board_gets_no_links_to_pages_it_cannot_open(board, client):
    """The Executive Board reads the overview but not the teacher sheets or the offerings.

    The links are only drawn for who can open them (review of T6.1).
    """
    client.force_login(board["ce"])
    html = client.get(url(board)).content.decode()
    assert "/teachers/" not in html
    assert "/offerings/" not in html
    client.force_login(board["manager"])
    assert "/teachers/" in client.get(url(board)).content.decode()


def test_a_teacher_of_another_coordination_is_marked_and_does_not_count_as_pending(board):
    """A teacher who moved away but still has a unit here is shown, marked, and kept out of
    the pending items, which this coordinator cannot act on (review of T6.1)."""
    from apps.dsd.models import TeachingUnit

    TeachingUnit.objects.filter(pk=unit_of(board, "A", "T").pk).update(teacher=board["foreign"])
    result = overview(board)
    rows = {row.teacher.identifier: row for row in result.rows}
    assert rows["T3"].foreign is True
    assert rows["T1"].foreign is False
    assert item(result, AttentionKind.REASON_MISSING).count == 2
    assert board["foreign"].pk not in item(result, AttentionKind.REASON_MISSING).teacher_ids


def test_a_dsd_without_the_semester_is_a_404(board, client):
    """No such semester: 404, not a server error."""
    from apps.dsd.models import DsdSemester

    DsdSemester.objects.filter(dsd=board["semester"].dsd, number=2).delete()
    client.force_login(board["coordinator"])
    assert client.get(url(board, 2)).status_code == 404
