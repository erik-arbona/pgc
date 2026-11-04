"""Tests that secrets never reach the append-only audit log.

Implements: CLAUDE.md rule 7 and D62. The audit log keeps old and new values of every change and
can never be edited, so a password hash written there could never be removed.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.core.audit import audited_save, snapshot
from apps.core.models import AuditEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def actor():
    """The user making the changes."""
    return get_user_model().objects.create_user(username="gestor", password="x")


def test_the_snapshot_of_a_user_leaves_out_the_password_and_last_login():
    """The excluded fields are not part of the snapshot."""
    user = get_user_model().objects.create_user(username="ana", password="segredo")
    values = snapshot(user)
    assert "password" not in values and "last_login" not in values
    assert values["username"] == "ana"


def test_no_audit_entry_of_a_user_contains_a_password_hash(actor):
    """Creating and updating an account never writes a hash into the log."""
    user = get_user_model()(username="ana")
    user.set_password("segredo-muito-longo")
    audited_save(user, actor)
    user.first_name = "Ana"
    audited_save(user, actor, "Nome")
    for entry in AuditEntry.objects.filter(entity="core.user"):
        text = f"{entry.old_value} {entry.new_value}"
        assert "pbkdf2_" not in text and "password" not in text
    assert AuditEntry.objects.filter(entity="core.user").count() == 2


def test_other_models_are_still_fully_snapshotted(actor):
    """Only the models that ask for exclusions lose fields."""
    from apps.academic.models import Faculty

    values = snapshot(Faculty(name="FCT", code="FCT"))
    assert set(values) == {"id", "name", "code"}
