"""Tests for the teacher sheet: who reads it, the lessons and the reading by the teacher (T6.3).

Implements: docs/backlog_fase2.md T6.3; D09 (teachers read their own distribution, read-only),
D69 (coordination scope), D100, docs/especificacao/07_arquitetura.md – teacher sheet.
"""

# The fixtures come from other test modules; F811 flags every test that uses them.
# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.models import Profile, ScopeKind
from apps.dsd.models import OtherActivity, TeachingUnit
from apps.dsd.services import (
    add_activity,
    assign_teacher,
    merge_units,
    review_minimum_reason,
    set_accepted_extra,
    set_minimum_reason,
)
from apps.dsd.tests.test_assignment import unit_of, user_with, world  # noqa: F401
from apps.dsd.tests.test_below_minimum import board, open_cell  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def own(board, django_user_model):
    """Teacher accounts: one linked to ``mine``, one linked to ``mine2`` (D09, D38)."""
    board["me"] = user_with(
        django_user_model, Profile.TEACHER, ScopeKind.TEACHER, board["mine"].pk, "tmine"
    )
    board["her"] = user_with(
        django_user_model, Profile.TEACHER, ScopeKind.TEACHER, board["mine2"].pk, "tmine2"
    )
    return board


def sheet(world, teacher=None):
    """The URL of the sheet of a teacher."""
    return reverse(
        "dsd:teacher_sheet", args=[world["semester"].dsd.pk, (teacher or world["mine"]).pk]
    )


def html_of(client, user, url):
    """The page, as a given user."""
    client.force_login(user)
    return client.get(url)


def test_who_reads_the_sheet(own, client):
    """The teacher themself, their coordinator, the manager and the board of the Faculty."""
    for user in (own["me"], own["coordinator"], own["manager"], own["ce"]):
        assert html_of(client, user, sheet(own)).status_code == 200


def test_who_does_not_read_the_sheet(own, client):
    """Another coordination, another teacher, an account linked to nobody, another Faculty."""
    for user in (own["other_coordinator"], own["her"], own["teacher_user"], own["other_ce"]):
        assert html_of(client, user, sheet(own)).status_code == 403


def test_the_sheet_needs_a_session(own, client):
    """Anonymous users go to the login."""
    assert client.get(sheet(own)).status_code == 302


def test_the_sheet_lists_the_lessons_of_the_teacher_by_semester(own, client):
    """Subject, class type, hours and the turma of each lesson the teacher gives."""
    open_cell(own)
    assign_teacher(own["coordinator"], unit_of(own, "A", "T"), own["mine"])
    assign_teacher(own["coordinator"], unit_of(own, "B", "P"), own["mine"])
    assign_teacher(own["coordinator"], unit_of(own, "A", "P"), own["mine2"])
    html = html_of(client, own["me"], sheet(own)).content.decode()
    assert html.count("Disciplina A1") == 2
    assert html.count('class="lesson"') == 2  # the other teacher's lesson is not listed


def test_a_merged_lesson_is_marked(own, client):
    """A unit that puts two turmas together shows the merge."""
    open_cell(own)
    units = [unit_of(own, "A", "T"), unit_of(own, "B", "T")]
    merge_units(own["coordinator"], units, 80)
    merged = TeachingUnit.objects.get(
        offering=own["offering"], class_type=own["T"], members__class_group_link=own["links"]["A"]
    )
    assign_teacher(own["coordinator"], merged, own["mine"])
    html = html_of(client, own["me"], sheet(own)).content.decode()
    assert "junção" in html


def test_the_teacher_reads_but_cannot_change_anything(own, client):
    """No link or form to add, change or remove: the teacher only reads (D09)."""
    open_cell(own)
    add_activity(
        own["coordinator"],
        own["mine"],
        own["semester"],
        OtherActivity.Kind.RESEARCH,
        "Projeto X",
        Decimal("2"),
    )
    set_accepted_extra(own["coordinator"], own["mine"], own["semester"].dsd, Decimal("2"))
    html = html_of(client, own["me"], sheet(own)).content.decode()
    assert "Projeto X" in html  # the teacher does read their other activities
    for forbidden in ("/activities/", "/extra/", "/below-minimum/", "Adicionar atividade"):
        assert forbidden not in html


def test_the_teacher_does_not_see_the_management_notes(own, client):
    """The reason for a low load and the board's comment are the coordinator's business."""
    open_cell(own)
    reason = set_minimum_reason(
        own["coordinator"], own["mine"], own["semester"].dsd, "Motivo reservado"
    )
    review_minimum_reason(own["ce"], reason, "refused", "Comentário reservado", reason.version)
    mine = html_of(client, own["me"], sheet(own)).content.decode()
    assert "Motivo reservado" not in mine and "Comentário reservado" not in mine
    assert "motivo recusado" not in mine and "motivo em falta" not in mine
    theirs = html_of(client, own["coordinator"], sheet(own)).content.decode()
    assert "Motivo reservado" in theirs and "Comentário reservado" in theirs


def test_the_teacher_sees_the_state_of_their_annual_load(own, client):
    """The state in words is part of what the teacher reads."""
    html = html_of(client, own["me"], sheet(own)).content.decode()
    assert "abaixo do mínimo" in html


def test_my_sheet_leads_to_the_latest_dsd(own, client):
    """A teacher account is sent to their own sheet; others are refused."""
    url = reverse("dsd:my_sheet")
    response = html_of(client, own["me"], url)
    assert response.status_code == 302
    assert response.url == sheet(own)
    for user in (own["coordinator"], own["teacher_user"]):
        assert html_of(client, user, url).status_code == 403


def test_the_menu_offers_my_sheet_only_to_teacher_accounts(own, client):
    """The link is cosmetic; the server checks anyway."""
    assert "A minha ficha" in html_of(client, own["me"], sheet(own)).content.decode()
    assert "A minha ficha" not in html_of(client, own["coordinator"], sheet(own)).content.decode()


def test_the_overview_links_only_the_sheets_the_viewer_can_open(own, client):
    """A teacher of another coordination is shown without a link to a sheet that would be 403."""
    TeachingUnit.objects.filter(pk=unit_of(own, "A", "T").pk).update(teacher=own["foreign"])
    url = reverse(
        "dsd:coordination_overview", args=[own["semester"].dsd.pk, own["coordination"].pk]
    )
    html = html_of(client, own["coordinator"], url).content.decode()
    assert f"/teachers/{own['mine'].pk}/" in html
    assert f"/teachers/{own['foreign'].pk}/" not in html


def test_the_lessons_cost_a_fixed_number_of_queries(own, client):
    """More lessons do not mean more queries (no N+1)."""
    open_cell(own)
    assign_teacher(own["coordinator"], unit_of(own, "A", "T"), own["mine"])
    client.force_login(own["coordinator"])
    client.get(sheet(own))  # warm caches that are not about the lessons
    with CaptureQueriesContext(connection) as before:
        client.get(sheet(own))
    for label, kind in (("A", "P"), ("B", "T"), ("B", "P")):
        assign_teacher(own["coordinator"], unit_of(own, label, kind), own["mine"])
    with CaptureQueriesContext(connection) as after:
        client.get(sheet(own))
    assert len(after) <= len(before)  # it must not grow with the lessons


def test_the_offering_page_links_only_the_sheets_the_viewer_can_open(own, client):
    """A teacher of another coordination holding a unit here shows without a link (D69)."""
    open_cell(own)
    assign_teacher(own["coordinator"], unit_of(own, "A", "P"), own["mine"])
    TeachingUnit.objects.filter(pk=unit_of(own, "A", "T").pk).update(teacher=own["foreign"])
    url = reverse("dsd:offering_detail", args=[own["offering"].pk])
    html = html_of(client, own["coordinator"], url).content.decode()
    assert f"/teachers/{own['mine'].pk}/" in html
    assert own["foreign"].name in html
    assert f"/teachers/{own['foreign'].pk}/" not in html
