"""Tests for the screens of the other activities of a teacher (T5.3).

Implements: docs/backlog_fase2.md T5.3; D15, D95, D86 (state of the cell), D69 (scope), D40
(reason), D54 (versions).
"""

# The ``world`` fixture comes from test_assignment; F811 flags every test that uses it.
# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.dsd.models import OtherActivity
from apps.dsd.services import add_activity, change_state
from apps.dsd.tests.test_assignment import world  # noqa: F401

pytestmark = pytest.mark.django_db

KIND = OtherActivity.Kind.RESEARCH


def open_cell(world):
    """Open the semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def sheet_url(world, teacher=None):
    """The sheet of a teacher."""
    return reverse(
        "dsd:teacher_sheet", args=[world["semester"].dsd.pk, (teacher or world["mine"]).pk]
    )


def add_url(world, number=1):
    """The page to add an activity to the teacher in a semester."""
    return reverse("dsd:activity_add", args=[world["semester"].dsd.pk, world["mine"].pk, number])


def make(world):
    """An activity of 3 hours of research, entered by the manager."""
    return add_activity(
        world["manager"], world["mine"], world["semester"], KIND, "Projeto X", Decimal("3")
    )


def test_the_sheet_shows_the_activities_and_the_totals(world, client):
    """Description, hours and the general total are on the page."""
    make(world)
    client.force_login(world["coordinator"])
    html = client.get(sheet_url(world)).content.decode()
    assert "Projeto X" in html
    assert "Total geral" in html
    assert "3,00" in html


def test_the_coordinator_adds_an_activity_from_the_screen(world, client):
    """POST creates it and goes back to the sheet."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = client.post(
        add_url(world), {"kind": KIND, "description": "Projeto Y", "weekly_hours": "2.5"}
    )
    assert response.status_code == 302
    assert response.url == sheet_url(world)
    assert OtherActivity.objects.get().weekly_hours == Decimal("2.50")


def test_the_add_screen_shows_the_error_of_a_closed_cell(world, client):
    """Not opened: the coordinator gets the message on the form, nothing is saved."""
    client.force_login(world["coordinator"])
    response = client.post(
        add_url(world), {"kind": KIND, "description": "Projeto Y", "weekly_hours": "2"}
    )
    assert response.status_code == 200
    assert OtherActivity.objects.count() == 0


def test_invalid_hours_are_shown_on_the_form(world, client):
    """Zero hours: the form refuses."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = client.post(add_url(world), {"kind": KIND, "description": "x", "weekly_hours": "0"})
    assert response.status_code == 200
    assert OtherActivity.objects.count() == 0


def test_a_coordinator_of_another_coordination_gets_403(world, client):
    """Scope by coordination on every activity screen (D69)."""
    open_cell(world)
    activity = make(world)
    client.force_login(world["other_coordinator"])
    assert client.get(add_url(world)).status_code == 403
    assert client.get(reverse("dsd:activity_edit", args=[activity.pk])).status_code == 403
    assert client.get(reverse("dsd:activity_remove", args=[activity.pk])).status_code == 403


def test_a_teacher_account_gets_403_on_the_activity_screens(world, client):
    """A teacher account only reads."""
    activity = make(world)
    client.force_login(world["teacher_user"])
    assert client.get(add_url(world)).status_code == 403
    assert client.post(reverse("dsd:activity_remove", args=[activity.pk])).status_code == 403


def test_the_edit_screen_changes_the_activity_with_a_reason(world, client):
    """Hours change; the reason is required."""
    open_cell(world)
    activity = make(world)
    url = reverse("dsd:activity_edit", args=[activity.pk])
    client.force_login(world["coordinator"])
    data = {
        "kind": KIND,
        "description": "Projeto X",
        "weekly_hours": "5",
        "seen": activity.version,
    }
    assert client.post(url, data).status_code == 200  # no reason
    assert OtherActivity.objects.get().weekly_hours == Decimal("3.00")
    response = client.post(url, {**data, "reason": "Mais horas"})
    assert response.status_code == 302
    assert OtherActivity.objects.get().weekly_hours == Decimal("5.00")


def test_the_edit_screen_requires_the_version(world, client):
    """A request without the version is rejected (D54)."""
    open_cell(world)
    activity = make(world)
    client.force_login(world["coordinator"])
    response = client.post(
        reverse("dsd:activity_edit", args=[activity.pk]),
        {"kind": KIND, "description": "x", "weekly_hours": "5", "reason": "r"},
    )
    assert response.status_code == 200
    assert OtherActivity.objects.get().description == "Projeto X"


def test_the_remove_screen_removes_with_a_reason(world, client):
    """The reason is required and the activity disappears."""
    open_cell(world)
    activity = make(world)
    url = reverse("dsd:activity_remove", args=[activity.pk])
    client.force_login(world["coordinator"])
    assert client.post(url, {"seen": activity.version}).status_code == 200
    assert OtherActivity.objects.count() == 1
    assert client.post(url, {"seen": activity.version, "reason": "Engano"}).status_code == 302
    assert OtherActivity.objects.count() == 0


def test_the_buttons_show_only_when_the_cell_is_writable(world, client):
    """Not opened: the coordinator sees no add link; the manager does (D86)."""
    make(world)
    client.force_login(world["coordinator"])
    assert "Adicionar atividade" not in client.get(sheet_url(world)).content.decode()
    client.force_login(world["manager"])
    assert "Adicionar atividade" in client.get(sheet_url(world)).content.decode()


def test_the_sheet_requires_a_session(world, client):
    """Anonymous users go to the login."""
    assert client.get(sheet_url(world)).status_code == 302


def test_after_a_transfer_the_buttons_follow_the_cell_of_each_activity(world, client):
    """The activity stays in the coordination where it was entered (review T5.3).

    The coordinator who owns the activity sees its change and remove links; the new coordinator
    of the teacher does not, because the screens would refuse them.
    """
    open_cell(world)
    change_state(world["manager"], "open", [world["semester"]], [world["foreign"].coordination])
    make(world)
    type(world["mine"]).objects.filter(pk=world["mine"].pk).update(
        coordination=world["foreign"].coordination
    )
    client.force_login(world["coordinator"])
    assert "/edit/" in client.get(sheet_url(world)).content.decode()
    client.force_login(world["other_coordinator"])
    assert "/edit/" not in client.get(sheet_url(world)).content.decode()
