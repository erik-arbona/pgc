"""Services of ``staff``: writes that touch more than one row.

Implements: CLAUDE.md rule 7 (audit of every change); D56.
"""

from __future__ import annotations

from django.db import transaction

from apps.core.audit import audited_delete

from .models import Teacher


def delete_teacher(teacher: Teacher, actor, reason: str) -> None:
    """Delete a teacher after deleting their position assignments, each with an audit entry.

    Args:
        teacher: the teacher to delete.
        actor: the user deleting them.
        reason: why (required, D40).

    Raises:
        ValidationError: if the reason is blank. Nothing is deleted.
        ProtectedError: if an account role still points at the teacher (D38).
    """
    with transaction.atomic():
        for row in teacher.position_assignments.all():
            audited_delete(row, actor, reason)
        audited_delete(teacher, actor, reason)
