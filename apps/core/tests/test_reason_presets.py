"""Tests for the reason presets of the data-entry forms.

Implements: CLAUDE.md rule 7 (audit with reason); D40 (reason required when editing and
deleting), D59 (a list of usual reasons, plus free text). Choosing a preset is enough; the free
text is optional detail, and it alone still works.
"""

import pytest
from django.urls import reverse

from apps.academic.models import ClassType
from apps.core.generic import REASON_CHOICES
from apps.core.models import AuditEntry

pytestmark = pytest.mark.django_db


def edit_url(item):
    """URL of the edit screen of a class type (a simple unscoped screen)."""
    return reverse("academic:classtype_update", kwargs={"pk": item.pk})


def edit_data(item, **overrides):
    """POST data that renames a class type, plus overrides."""
    data = {"code": item.code, "name": "Renomeada", "position": item.position, "is_active": "on"}
    data.update(overrides)
    return data


@pytest.fixture
def item():
    """An existing class type."""
    return ClassType.objects.get(code="OUT")


def label(key):
    """The label of a preset."""
    return str(dict(REASON_CHOICES)[key])


def test_the_presets_cover_the_usual_reasons():
    """The list starts with an empty choice and offers the usual reasons."""
    keys = [key for key, _ in REASON_CHOICES]
    assert keys[0] == ""
    assert {
        "correction",
        "plan_change",
        "board_decision",
        "data_update",
        "created_by_mistake",
    } <= set(keys)


def test_a_preset_alone_is_enough_to_edit(manager_client, item):
    """One click: the preset's text becomes the audit reason."""
    manager_client.post(edit_url(item), edit_data(item, reason_choice="correction"))
    item.refresh_from_db()
    assert item.name == "Renomeada"
    assert AuditEntry.objects.get().reason == label("correction")


def test_free_text_alone_still_works(manager_client, item):
    """Writing the reason, as before, is accepted."""
    manager_client.post(edit_url(item), edit_data(item, reason="Texto livre"))
    assert AuditEntry.objects.get().reason == "Texto livre"


def test_a_preset_and_text_are_combined(manager_client, item):
    """The preset gives the category and the text the detail."""
    manager_client.post(
        edit_url(item), edit_data(item, reason_choice="plan_change", reason="Plano 2027")
    )
    assert AuditEntry.objects.get().reason == f"{label('plan_change')}: Plano 2027"


def test_editing_without_any_reason_is_refused(manager_client, item):
    """Neither a preset nor text: error on the reason, nothing changes."""
    response = manager_client.post(edit_url(item), edit_data(item))
    assert response.status_code == 200
    assert "reason" in response.context["form"].errors
    item.refresh_from_db()
    assert item.name == "Outra"
    assert not AuditEntry.objects.exists()


def test_an_unknown_preset_is_refused(manager_client, item):
    """Only the listed presets are accepted."""
    response = manager_client.post(edit_url(item), edit_data(item, reason_choice="inventado"))
    assert response.status_code == 200
    assert "reason_choice" in response.context["form"].errors


def test_creating_needs_no_reason(manager_client):
    """A new record needs no reason (D40)."""
    manager_client.post(
        reverse("academic:classtype_create"),
        {"code": "S", "name": "Seminário", "position": 60, "is_active": "on"},
    )
    assert ClassType.objects.filter(code="S").exists()


def test_deleting_accepts_a_preset(manager_client, item):
    """The delete page also offers the presets."""
    url = reverse("academic:classtype_delete", kwargs={"pk": item.pk})
    manager_client.post(url, {})
    assert ClassType.objects.filter(pk=item.pk).exists()
    manager_client.post(url, {"reason_choice": "created_by_mistake"})
    assert not ClassType.objects.filter(pk=item.pk).exists()
    assert AuditEntry.objects.get().reason == label("created_by_mistake")


def test_the_preset_selector_comes_just_before_the_reason_text(manager_client, item):
    """The two reason fields stay together at the end of the form."""
    form = manager_client.get(edit_url(item)).context["form"]
    names = list(form.fields)
    assert names[-2:] == ["reason_choice", "reason"]
