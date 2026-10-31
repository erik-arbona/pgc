"""Tests for the generic audit log.

Implements: docs/especificacao/07_arquitetura.md – Versions and audit
(who, when, previous value, new value and reason).
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.core.audit import audited_delete, audited_save
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind

User = get_user_model()


@pytest.fixture
def actor(db):
    """The user performing the changes."""
    return User.objects.create_user(username="admin1", password="x")


@pytest.fixture
def target(db):
    """A user who receives a role (the audited entity's owner)."""
    return User.objects.create_user(username="bob", password="x")


def new_assignment(target, **overrides):
    """Build an unsaved RoleAssignment."""
    data = dict(user=target, profile=Profile.COORDINATOR, scope_kind=ScopeKind.COORDINATION)
    data.update(scope_id=1)
    data.update(overrides)
    return RoleAssignment(**data)


def test_create_records_who_when_and_the_new_value_without_a_previous_one(actor, target):
    """A creation logs the actor, a timestamp, no old value and the new field values."""
    assignment = new_assignment(target)
    audited_save(assignment, actor)

    entry = AuditEntry.objects.get()
    assert entry.actor == actor
    assert entry.created_at is not None
    assert entry.action == AuditEntry.Action.CREATE
    assert entry.entity == "core.roleassignment"
    assert entry.entity_id == str(assignment.pk)
    assert entry.old_value is None
    assert entry.new_value["profile"] == "coordinator"
    assert entry.new_value["scope_id"] == 1


def test_update_records_previous_and_new_values_and_the_reason(actor, target):
    """An update logs the values before and after the change, and why it was made."""
    assignment = new_assignment(target)
    audited_save(assignment, actor)

    assignment.scope_id = 2
    audited_save(assignment, actor, reason="Moved to another coordination")

    entry = AuditEntry.objects.filter(action=AuditEntry.Action.UPDATE).get()
    assert entry.old_value["scope_id"] == 1
    assert entry.new_value["scope_id"] == 2
    assert entry.reason == "Moved to another coordination"


def test_update_without_a_reason_is_rejected_and_changes_nothing(actor, target):
    """Updates need a reason (D40): nothing is saved or logged without one."""
    assignment = new_assignment(target)
    audited_save(assignment, actor)

    assignment.scope_id = 2
    with pytest.raises(ValidationError):
        audited_save(assignment, actor)

    assignment.refresh_from_db()
    assert assignment.scope_id == 1
    assert AuditEntry.objects.count() == 1


def test_delete_records_the_previous_value_and_needs_a_reason(actor, target):
    """A deletion logs the last known values and the reason; without a reason it is rejected."""
    assignment = new_assignment(target)
    audited_save(assignment, actor)
    pk = assignment.pk

    with pytest.raises(ValidationError):
        audited_delete(assignment, actor)
    assert RoleAssignment.objects.filter(pk=pk).exists()

    audited_delete(assignment, actor, reason="Left the coordination")

    assert not RoleAssignment.objects.filter(pk=pk).exists()
    entry = AuditEntry.objects.get(action=AuditEntry.Action.DELETE)
    assert entry.entity_id == str(pk)
    assert entry.old_value["profile"] == "coordinator"
    assert entry.new_value is None
    assert entry.reason == "Left the coordination"


def test_change_and_audit_entry_are_saved_in_the_same_transaction(target):
    """If the audit entry cannot be written, the change is rolled back too."""
    unsaved_actor = User(username="ghost")  # never saved: the entry cannot reference it
    with pytest.raises(ValueError):
        audited_save(new_assignment(target), unsaved_actor)

    assert RoleAssignment.objects.count() == 0
    assert AuditEntry.objects.count() == 0


def test_existing_entries_cannot_be_modified(actor, target):
    """The log is append-only: saving an existing entry is refused."""
    audited_save(new_assignment(target), actor)
    entry = AuditEntry.objects.get()
    entry.reason = "rewritten"
    with pytest.raises(PermissionError):
        entry.save()


def test_entries_cannot_be_deleted_one_by_one_or_in_bulk(actor, target):
    """The log is append-only: neither instance nor queryset deletes/updates are allowed."""
    audited_save(new_assignment(target), actor)
    entry = AuditEntry.objects.get()
    with pytest.raises(PermissionError):
        entry.delete()
    with pytest.raises(PermissionError):
        AuditEntry.objects.all().delete()
    with pytest.raises(PermissionError):
        AuditEntry.objects.all().update(reason="rewritten")
    assert AuditEntry.objects.count() == 1


def test_values_with_dates_and_foreign_keys_are_stored_as_json(actor, target):
    """Foreign keys are stored by id so any model can be audited."""
    assignment = new_assignment(target)
    audited_save(assignment, actor)
    assert AuditEntry.objects.get().new_value["user"] == target.pk
