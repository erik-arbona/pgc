"""Tests for the screens and texts of the accepted extra hours (T5.4).

Implements: docs/backlog_fase2.md T5.4; D13, D96, D86, D69, D40, D54.
"""

# The ``world`` fixture comes from test_assignment; F811 flags every test that uses it.
# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.dsd.extra_hours import assess_extra
from apps.dsd.load_facts import extra_text
from apps.dsd.models import AcceptedExtraHours
from apps.dsd.services import change_state, set_accepted_extra
from apps.dsd.tests.test_assignment import world  # noqa: F401

pytestmark = pytest.mark.django_db

D = Decimal


def open_cell(world):
    """Open the first semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def accept_url(world):
    """The page to record the accepted hours of the teacher."""
    return reverse("dsd:extra_accept", args=[world["semester"].dsd.pk, world["mine"].pk])


def sheet_url(world):
    """The sheet of the teacher."""
    return reverse("dsd:teacher_sheet", args=[world["semester"].dsd.pk, world["mine"].pk])


def record(world):
    """A record of 4 accepted hours made by the manager."""
    return set_accepted_extra(world["manager"], world["mine"], world["semester"].dsd, D("4"))


def test_the_text_says_nothing_without_an_excess():
    """No excess: no text."""
    assert extra_text(assess_extra(D("0"), D("0"))) == ""


def test_the_text_says_accepted_when_the_acceptance_covers_the_excess():
    """Excess 3, accepted 4."""
    assert "aceites" in extra_text(assess_extra(D("3"), D("4")))


def test_the_text_says_what_is_pending():
    """Excess 6, accepted 4: 2 hours pending."""
    text = extra_text(assess_extra(D("6"), D("4")))
    assert "por aceitar" in text and "2.00" in text


def test_the_coordinator_records_the_hours_from_the_screen(world, client):
    """POST creates the record and goes back to the sheet."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = client.post(accept_url(world), {"hours": "3"})
    assert response.status_code == 302
    assert response.url == sheet_url(world)
    assert AcceptedExtraHours.objects.get().hours == D("3.00")


def test_changing_from_the_screen_needs_version_and_reason(world, client):
    """Without them the form is shown again and nothing changes."""
    open_cell(world)
    existing = record(world)
    client.force_login(world["coordinator"])
    assert client.post(accept_url(world), {"hours": "5", "reason": "r"}).status_code == 200
    assert (
        client.post(accept_url(world), {"hours": "5", "seen": existing.version}).status_code == 200
    )
    assert AcceptedExtraHours.objects.get().hours == D("4.00")
    data = {"hours": "5", "seen": existing.version, "reason": "Aceitou mais"}
    assert client.post(accept_url(world), data).status_code == 302
    assert AcceptedExtraHours.objects.get().hours == D("5.00")


def test_clearing_from_the_screen_needs_a_reason(world, client):
    """The record is removed with a reason."""
    open_cell(world)
    existing = record(world)
    url = reverse("dsd:extra_clear", args=[existing.pk])
    client.force_login(world["coordinator"])
    assert client.post(url, {"seen": existing.version}).status_code == 200
    assert AcceptedExtraHours.objects.count() == 1
    assert client.post(url, {"seen": existing.version, "reason": "Recusou"}).status_code == 302
    assert AcceptedExtraHours.objects.count() == 0


def test_other_coordinators_and_teacher_accounts_get_403(world, client):
    """Scope and profile on every extra-hours screen."""
    open_cell(world)
    existing = record(world)
    for user in (world["other_coordinator"], world["teacher_user"]):
        client.force_login(user)
        assert client.get(accept_url(world)).status_code == 403
        assert client.get(reverse("dsd:extra_clear", args=[existing.pk])).status_code == 403


def test_the_sheet_shows_the_accepted_hours_and_the_buttons_follow_the_cell(world, client):
    """The hours show; the change link shows only to who may write (D86)."""
    record(world)
    client.force_login(world["coordinator"])
    html = client.get(sheet_url(world)).content.decode()
    assert "Horas extra aceites" in html and "4,00" in html
    assert "/extra/" not in html  # the cell is not opened: the coordinator cannot write
    client.force_login(world["manager"])
    assert "/extra/" in client.get(sheet_url(world)).content.decode()
