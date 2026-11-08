"""Tests for the reports of the Executive Board (T6.8).

Implements: docs/especificacao/05_dsd_regras.md (the board has its own reports: teachers below the
minimum with their reasons, below the maximum, with extra hours); docs/backlog_fase2.md T6.8;
D16, D69 (scope by Faculty), D104.
"""

# The fixtures come from other test modules; F811 flags every test that uses them.
# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.dsd.board_report import board_report
from apps.dsd.extra_hours import ExtraStatus
from apps.dsd.load_status import LoadStatus
from apps.dsd.reports import ReportKind, free_hours, reports_of
from apps.dsd.services import assign_teacher, set_minimum_reason
from apps.dsd.tests.test_assignment import make_teacher, unit_of, world  # noqa: F401
from apps.dsd.tests.test_below_minimum import board, open_cell  # noqa: F401
from apps.staff.models import LoadRange

pytestmark = pytest.mark.django_db

D = Decimal


# --- the pure rules ----------------------------------------------------------------------------


def test_each_state_of_the_load_belongs_to_one_report():
    """Below the minimum, in range and above the maximum; at the maximum and no range, none."""
    assert reports_of(LoadStatus.BELOW_MINIMUM, ExtraStatus.NONE) == {ReportKind.BELOW_MINIMUM}
    assert reports_of(LoadStatus.IN_RANGE, ExtraStatus.NONE) == {ReportKind.BELOW_MAXIMUM}
    assert reports_of(LoadStatus.ABOVE_MAXIMUM, ExtraStatus.PENDING) == {ReportKind.EXTRA_HOURS}
    assert reports_of(LoadStatus.ABOVE_MAXIMUM, ExtraStatus.ACCEPTED) == {ReportKind.EXTRA_HOURS}
    assert reports_of(LoadStatus.AT_MAXIMUM, ExtraStatus.NONE) == set()
    assert reports_of(LoadStatus.NO_RANGE, ExtraStatus.NONE) == set()


def test_the_free_hours_are_what_is_left_up_to_the_maximum():
    """12 h maximum and 7 h given leave 5 h; never negative; nothing without a range."""
    assert free_hours(D("12"), D("7")) == D("5.00")
    assert free_hours(D("12"), D("12")) == D("0.00")
    assert free_hours(D("12"), D("15")) == D("0.00")
    assert free_hours(None, D("7")) is None


# --- the data ----------------------------------------------------------------------------------


def report(world):
    """The report of the Faculty of the demo coordinations."""
    covered = {world["coordination"].pk, world["foreign"].coordination_id}
    return board_report(world["semester"].dsd, covered)


def names(rows):
    """The teacher identifiers of some rows, sorted."""
    return sorted(row.teacher.identifier for row in rows)


def give(world, who, *units):
    """Give the units, as (turma label, class type), to a teacher."""
    for label, kind in units:
        assign_teacher(world["coordinator"], unit_of(world, label, kind), who)


def test_below_the_minimum_in_range_and_extra_hours_are_listed_apart(board):
    """T1 has 7 h in a range of 6-12 (in range); T2 has 3 h (below); T3 and the rest are 0 h."""
    open_cell(board)
    give(board, board["mine"], ("A", "T"), ("A", "P"), ("B", "T"))
    give(board, board["mine2"], ("B", "P"))
    result = report(board)
    assert names(result.below_minimum) == ["T2", "T3"]
    assert names(result.below_maximum) == ["T1"]
    assert result.extra_hours == []


def test_the_free_hours_of_a_teacher_in_range_are_shown(board):
    """T1: maximum 12 and 7 h given leave 5 h."""
    open_cell(board)
    give(board, board["mine"], ("A", "T"), ("A", "P"), ("B", "T"))
    row = next(r for r in report(board).below_maximum if r.teacher.identifier == "T1")
    assert row.free_hours == D("5.00")


def test_the_extra_hours_show_the_excess_and_what_is_not_accepted_yet(board):
    """With a maximum of 8 h and 10 h given, the excess is 2 h and none is accepted."""
    LoadRange.objects.update(maximum_hours=D("8"))
    open_cell(board)
    give(board, board["mine"], ("A", "T"), ("A", "P"), ("B", "T"), ("B", "P"))
    [row] = report(board).extra_hours
    assert row.teacher.identifier == "T1"
    assert row.load.extra.extra_hours == D("2.00")
    assert row.load.extra.pending_hours == D("2.00")


def test_a_teacher_below_the_minimum_carries_the_reason_and_its_state(board):
    """The board decides on it, so it reads it."""
    open_cell(board)
    set_minimum_reason(
        board["coordinator"], board["mine"], board["semester"].dsd, "Licença parcial"
    )
    row = next(r for r in report(board).below_minimum if r.teacher.identifier == "T1")
    assert row.reason.text == "Licença parcial"


def test_inactive_teachers_are_left_out(board):
    """Only active teachers have a load to review."""
    everyone = names(report(board).below_minimum)
    assert "T4" not in everyone


def test_the_report_does_not_grow_in_queries_with_more_teachers(board):
    """No N+1: more teachers, no more queries."""
    report(board)  # warm the caches that are not about the teachers
    with CaptureQueriesContext(connection) as before:
        report(board)
    for index in range(5, 10):
        make_teacher(board["coordination"], f"T{index}")
    with CaptureQueriesContext(connection) as after:
        report(board)
    assert len(after) <= len(before)


# --- the screens -------------------------------------------------------------------------------


def url(world):
    """The page of the reports of a DSD."""
    return reverse("dsd:board_report", args=[world["semester"].dsd.pk])


def test_the_board_reads_the_report_of_its_faculty(board, client):
    """The three sections, with the teachers of the Faculty and a reason text."""
    open_cell(board)
    set_minimum_reason(
        board["coordinator"], board["mine"], board["semester"].dsd, "Licença parcial"
    )
    client.force_login(board["ce"])
    response = client.get(url(board))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Abaixo da mínima" in html and "Abaixo da máxima" in html and "Horas extra" in html
    assert board["mine"].name in html
    assert "Licença parcial" in html


def test_only_the_board_reads_the_reports(board, client):
    """The coordinator, the manager and teacher accounts are refused; anonymous users log in."""
    assert client.get(url(board)).status_code == 302
    for user in (board["coordinator"], board["manager"], board["teacher_user"]):
        client.force_login(user)
        assert client.get(url(board)).status_code == 403


def test_the_board_of_another_faculty_sees_none_of_these_teachers(board, client):
    """A board with its own Faculty reads its own reports only (D69)."""
    client.force_login(board["other_ce"])
    response = client.get(url(board))
    assert response.status_code == 200
    html = response.content.decode()
    assert board["mine"].name not in html and board["foreign"].name not in html


def test_the_menu_offers_the_reports_to_the_board_only(board, client):
    """The link is cosmetic; the server checks anyway."""
    client.force_login(board["ce"])
    assert "Relatórios" in client.get(url(board)).content.decode()
    client.force_login(board["coordinator"])
    page = reverse("dsd:dsd_detail", args=[board["semester"].dsd.pk])
    assert "Relatórios" not in client.get(page).content.decode()


def test_the_reports_home_leads_to_the_latest_dsd(board, client):
    """The menu link does not know the DSD: it goes to the latest one."""
    home = reverse("dsd:board_report_home")
    client.force_login(board["ce"])
    response = client.get(home)
    assert response.status_code == 302
    assert response.url == url(board)
    client.force_login(board["coordinator"])
    assert client.get(home).status_code == 403
