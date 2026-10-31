"""Audited writes: save or delete a record and log it in the same transaction.

Implements: docs/especificacao/07_arquitetura.md – Versions and audit; CLAUDE.md rule 7.
Every change to business data must go through ``audited_save`` / ``audited_delete``.
See D40 for when a reason is required.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from .models import AuditEntry


def snapshot(instance: models.Model) -> dict[str, Any]:
    """Return the concrete field values of a record, foreign keys as ids.

    Args:
        instance: any saved or unsaved model instance.

    Returns:
        A dict of field name to value (JSON-encodable by ``DjangoJSONEncoder``).
    """
    return {f.name: f.value_from_object(instance) for f in instance._meta.concrete_fields}


def _entity_label(instance: models.Model) -> str:
    """Return the model label stored in ``AuditEntry.entity`` (e.g. ``core.roleassignment``)."""
    return instance._meta.label_lower


def _require_reason(reason: str) -> None:
    """Raise if the reason is blank.

    Raises:
        ValidationError: if ``reason`` is empty or only whitespace.
    """
    if not reason.strip():
        raise ValidationError({"reason": _("O motivo é obrigatório.")})


def audited_save(instance: models.Model, actor, reason: str = "") -> AuditEntry:
    """Create or update a record and log the change atomically.

    Args:
        instance: the record to save.
        actor: the user making the change.
        reason: why; required when the record already exists (update).

    Returns:
        The audit entry written.

    Raises:
        ValidationError: if updating without a reason.
    """
    creating = instance._state.adding
    if not creating:
        _require_reason(reason)
    with transaction.atomic():
        old = None if creating else snapshot(type(instance)._default_manager.get(pk=instance.pk))
        instance.save()
        return AuditEntry.objects.create(
            actor=actor,
            entity=_entity_label(instance),
            entity_id=str(instance.pk),
            action=AuditEntry.Action.CREATE if creating else AuditEntry.Action.UPDATE,
            old_value=old,
            new_value=snapshot(instance),
            reason=reason,
        )


def audited_delete(instance: models.Model, actor, reason: str = "") -> AuditEntry:
    """Delete a record and log the deletion atomically.

    Args:
        instance: the saved record to delete.
        actor: the user making the change.
        reason: why; always required.

    Returns:
        The audit entry written.

    Raises:
        ValidationError: if the reason is blank.
    """
    _require_reason(reason)
    with transaction.atomic():
        old = snapshot(instance)
        entity_id = str(instance.pk)  # captured before delete() clears the primary key
        instance.delete()
        return AuditEntry.objects.create(
            actor=actor,
            entity=_entity_label(instance),
            entity_id=entity_id,
            action=AuditEntry.Action.DELETE,
            old_value=old,
            new_value=None,
            reason=reason,
        )
