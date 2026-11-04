"""Tests for the configurable system parameters.

Implements: CLAUDE.md rule 6 (parameters, not constants); D60 (weeks per semester, 15 by
default). The values are entered by the PGC manager and every change is audited with a reason.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.core.models import AuditEntry, Parameter, Profile
from apps.core.parameters import SEMESTER_WEEKS, get_parameter
from apps.core.permissions import can

pytestmark = pytest.mark.django_db


def test_the_weeks_per_semester_are_loaded_by_the_migration_with_value_15():
    """15 weeks in each semester, as the PGC manager stated (D60)."""
    assert get_parameter(SEMESTER_WEEKS) == Decimal("15")


def test_get_parameter_returns_the_current_value():
    """A changed value is the one returned."""
    parameter = Parameter.objects.get(code=SEMESTER_WEEKS)
    parameter.value = Decimal("16")
    parameter.save()
    assert get_parameter(SEMESTER_WEEKS) == Decimal("16")


def test_an_unknown_parameter_fails_closed():
    """A missing parameter is an error, never a silent default."""
    with pytest.raises(LookupError):
        get_parameter("inventado")


def test_the_code_is_unique():
    """Two parameters cannot share a code."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Parameter.objects.create(code=SEMESTER_WEEKS, name="Outro", value=Decimal("1"))


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1")])
def test_the_value_must_be_positive(value):
    """Zero or negative values are refused by the database."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Parameter.objects.create(code="x", name="X", value=value)


def test_anonymous_visitors_are_redirected_to_login(client):
    """The list requires a session."""
    response = client.get(reverse("core:parameter_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, profile):
    """Only the PGC manager reaches the parameter screens."""
    client.force_login(make_user(profile))
    item = Parameter.objects.get(code=SEMESTER_WEEKS)
    for name, kwargs in (("list", {}), ("update", {"pk": item.pk})):
        url = reverse(f"core:parameter_{name}", kwargs=kwargs)
        assert client.get(url).status_code == 403
        assert client.post(url, {"value": "20", "reason": "x"}).status_code == 403
    item.refresh_from_db()
    assert item.value == Decimal("15")
    assert not AuditEntry.objects.exists()


def test_a_superuser_without_assignment_gets_403(client):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse("core:parameter_list")).status_code == 403


def test_the_list_shows_the_parameters(manager_client):
    """The weeks per semester appear with their value."""
    page = manager_client.get(reverse("core:parameter_list")).content.decode()
    assert "Semanas por semestre" in page and "15" in page


def test_changing_a_value_needs_a_reason_and_is_audited(manager_client):
    """No reason: refused. With a reason: changed, with old and new values logged."""
    item = Parameter.objects.get(code=SEMESTER_WEEKS)
    url = reverse("core:parameter_update", kwargs={"pk": item.pk})
    manager_client.post(url, {"value": "16"})
    item.refresh_from_db()
    assert item.value == Decimal("15") and not AuditEntry.objects.exists()
    manager_client.post(url, {"value": "16", "reason_choice": "data_update"})
    item.refresh_from_db()
    assert item.value == Decimal("16")
    entry = AuditEntry.objects.get()
    assert (Decimal(entry.old_value["value"]), Decimal(entry.new_value["value"])) == (
        Decimal("15"),
        Decimal("16"),
    )


@pytest.mark.parametrize("value", ["0", "-3", "abc"])
def test_an_invalid_value_is_a_form_error(manager_client, value):
    """Zero, negative and non-numeric values are refused with a message on the form."""
    item = Parameter.objects.get(code=SEMESTER_WEEKS)
    response = manager_client.post(
        reverse("core:parameter_update", kwargs={"pk": item.pk}),
        {"value": value, "reason": "Teste"},
    )
    assert response.status_code == 200
    assert "value" in response.context["form"].errors
    item.refresh_from_db()
    assert item.value == Decimal("15")


def test_the_name_and_code_cannot_be_changed_from_the_screen(manager_client):
    """Only the value is editable."""
    item = Parameter.objects.get(code=SEMESTER_WEEKS)
    manager_client.post(
        reverse("core:parameter_update", kwargs={"pk": item.pk}),
        {"value": "14", "name": "Hackeado", "code": "hack", "reason": "Teste"},
    )
    item.refresh_from_db()
    assert (item.code, item.name, item.value) == (SEMESTER_WEEKS, "Semanas por semestre", 14)


@pytest.mark.parametrize("profile", list(Profile))
def test_only_the_pgc_manager_has_the_parameter_action(make_user, profile):
    """parameter.edit belongs to the PGC manager alone and needs no scope."""
    assert can(make_user(profile), "parameter.edit") is (profile == Profile.PGC_MANAGER)


def test_menu_shows_the_parameters_link(manager_client):
    """The screen appears in the manager's menu."""
    assert reverse("core:parameter_list") in manager_client.get("/").content.decode()
