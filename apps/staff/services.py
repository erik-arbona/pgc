"""Services of ``staff``: writes that touch more than one row.

Implements: CLAUDE.md rule 7 (audit of every change); D56.
"""

from __future__ import annotations

from collections.abc import Collection

from django.db import transaction

from apps.core.audit import audited_delete, audited_save

from .models import Position, Teacher, TeacherPosition


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


def save_teacher_with_positions(
    teacher: Teacher,
    position_ids: Collection[int],
    actor,
    reason: str,
    *,
    save_teacher: bool,
) -> None:
    """Save a teacher and their positions in one audited transaction (D56).

    Each row written (the teacher, and every position assignment created or removed) gets its
    own audit entry sharing the same reason; rows that do not change write nothing. The
    positions to remove are deleted before the teacher is saved, so a full-time teacher can
    stop being full-time in the same save that removes their positions.

    Args:
        teacher: the teacher, new or existing.
        position_ids: ids of the positions the teacher must hold afterwards.
        actor: the user making the change.
        reason: why; required when the teacher already exists (D40).
        save_teacher: whether the teacher's own fields changed and must be saved.

    Raises:
        ValidationError: if a row is refused (for example a missing reason on an update, an
            inactive position, or positions on a teacher that is not full-time). Nothing is
            saved in that case.
    """
    wanted = set(position_ids)
    with transaction.atomic():
        existing = (
            {}
            if teacher._state.adding
            else {row.position_id: row for row in teacher.position_assignments.all()}
        )
        for position_id, row in existing.items():
            if position_id not in wanted:
                audited_delete(row, actor, reason)
        if save_teacher or teacher._state.adding:
            audited_save(teacher, actor, reason)
        for position in Position.objects.filter(pk__in=wanted - set(existing)):
            audited_save(TeacherPosition(teacher=teacher, position=position), actor, reason)
