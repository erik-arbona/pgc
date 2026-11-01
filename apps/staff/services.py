"""Services of ``staff``: writes that touch more than one row.

Implements: CLAUDE.md rule 7 (audit of every change); D56.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.audit import audited_delete, audited_save

from .load_ranges import ResolvedRange, TeacherFacts, resolve_load_range
from .models import LoadRange, Position, Teacher, TeacherPosition


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


# --- hours ranges (T3.2, D58) ------------------------------------------------------------------


def load_ranges_for(
    teachers: Iterable[Teacher], as_of: date | None = None
) -> dict[int, ResolvedRange | None]:
    """Return the hours range of each teacher on a date, with a fixed number of queries.

    Args:
        teachers: saved teachers.
        as_of: the date; today by default.

    Returns:
        A dict from teacher id to the resolved range (``None`` when no rule is in force).
    """
    as_of = as_of or timezone.localdate()
    people = list(teachers)
    positions: dict[int, set[int]] = {}
    for teacher_id, position_id in TeacherPosition.objects.filter(
        teacher_id__in=[t.pk for t in people]
    ).values_list("teacher_id", "position_id"):
        positions.setdefault(teacher_id, set()).add(position_id)
    rules = [rule.to_rule() for rule in LoadRange.objects.all()]
    return {
        t.pk: resolve_load_range(
            rules,
            TeacherFacts(t.teacher_type, t.category_id, frozenset(positions.get(t.pk, ()))),
            as_of,
        )
        for t in people
    }


def load_range_for(teacher: Teacher, as_of: date | None = None) -> ResolvedRange | None:
    """Return the hours range of one teacher on a date (today by default)."""
    return load_ranges_for([teacher], as_of)[teacher.pk]


def _hours_errors(rule: LoadRange) -> list[str]:
    """Return the messages for an inconsistent rule (empty when it is valid)."""
    errors: list[str] = []
    reference = {
        LoadRange.Kind.CATEGORY: rule.category_id,
        LoadRange.Kind.POSITION: rule.position_id,
        LoadRange.Kind.TEACHER_TYPE: rule.teacher_type,
    }.get(rule.kind)
    if not reference:
        errors.append(str(_("Indique a categoria, o cargo ou o tipo de docente da regra.")))
    if rule.kind == LoadRange.Kind.TEACHER_TYPE and rule.teacher_type == Teacher.Type.FULL_TIME:
        errors.append(
            str(_("Os docentes a tempo inteiro usam intervalos por categoria e por cargo."))
        )
    if rule.maximum_hours is None or rule.maximum_hours < 0:
        errors.append(str(_("O máximo tem de ser zero ou mais.")))
    if rule.minimum_hours is None:
        if rule.kind != LoadRange.Kind.TEACHER_TYPE:
            errors.append(str(_("O mínimo é obrigatório nas categorias e nos cargos.")))
    else:
        if rule.minimum_hours < 0:
            errors.append(str(_("O mínimo tem de ser zero ou mais.")))
        if rule.maximum_hours is not None and rule.minimum_hours > rule.maximum_hours:
            errors.append(str(_("O mínimo não pode ser superior ao máximo.")))
    return errors


def _require_not_in_force(stored: LoadRange, today: date) -> None:
    """Refuse to change or delete a rule that has already started (D58)."""
    if stored.valid_from <= today:
        raise ValidationError(
            str(
                _(
                    "Esta regra já está em vigor e não se altera nem se apaga: "
                    "acrescente uma regra com data posterior."
                )
            )
        )


def save_load_range(rule: LoadRange, actor, reason: str, *, today: date | None = None):
    """Create or update a rule through the audit log (D58).

    A new rule may have any start date. An existing rule can be changed only while it has not
    started (its start date is after today), and its subject (kind and reference) never changes.
    Two rules of one subject cannot start on the same day.

    Args:
        rule: the rule, new or existing.
        actor: the user making the change.
        reason: why; required when the rule already exists (D40).
        today: the current date; defaults to the local date (a parameter for tests).

    Returns:
        The audit entry written.

    Raises:
        ValidationError: if the rule is inconsistent, overlaps another, is already in force or
            changes its subject, or if the reason is missing on an update.
    """
    today = today or timezone.localdate()
    if rule.pk:
        stored = LoadRange.objects.get(pk=rule.pk)
        _require_not_in_force(stored, today)
        subject = (rule.kind, rule.category_id, rule.position_id, rule.teacher_type)
        if subject != (stored.kind, stored.category_id, stored.position_id, stored.teacher_type):
            raise ValidationError(
                str(_("A categoria, o cargo ou o tipo de uma regra não se altera."))
            )
    errors = _hours_errors(rule)
    if errors:
        raise ValidationError(errors)
    same_start = LoadRange.objects.filter(
        kind=rule.kind,
        category_id=rule.category_id,
        position_id=rule.position_id,
        teacher_type=rule.teacher_type,
        valid_from=rule.valid_from,
    ).exclude(pk=rule.pk)
    if same_start.exists():
        raise ValidationError(str(_("Já existe uma regra deste sujeito com esta data de início.")))
    return audited_save(rule, actor, reason)


def delete_load_range(rule: LoadRange, actor, reason: str, *, today: date | None = None):
    """Delete a rule that has not started yet, through the audit log (D58).

    Args:
        rule: the rule to delete.
        actor: the user deleting it.
        reason: why (required, D40).
        today: the current date; defaults to the local date.

    Returns:
        The audit entry written.

    Raises:
        ValidationError: if the rule is already in force or the reason is missing.
    """
    today = today or timezone.localdate()
    _require_not_in_force(LoadRange.objects.get(pk=rule.pk), today)
    return audited_delete(rule, actor, reason)
