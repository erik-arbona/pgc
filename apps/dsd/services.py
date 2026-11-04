"""Use cases of the DSD: create the DSD of an academic year (T2.1).

Implements: docs/backlog_fase2.md T2.1 and T2.2; D43 (one DSD per academic year, created by the
manager, who also opens, closes and reopens the semesters by coordination).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.academic.models import AcademicYear, Coordination
from apps.core.audit import audited_save
from apps.core.permissions import registry

from .lifecycle_rules import needs_reason, next_state
from .models import CoordinationSemester, Dsd, DsdSemester

SEMESTER_NUMBERS = (1, 2)


def _existing_dsd(academic_year: AcademicYear) -> Dsd | None:
    """Return the DSD of the academic year, or ``None`` (the friendly pre-check)."""
    return Dsd.objects.filter(academic_year=academic_year).first()


def _already_exists(academic_year: AcademicYear) -> ValidationError:
    """Build the error shown when the academic year already has a DSD."""
    return ValidationError(
        _("Já existe um DSD para o ano letivo %(year)s.") % {"year": academic_year.label}
    )


def create_dsd(academic_year: AcademicYear, actor, reason: str = "") -> Dsd:
    """Create the DSD of an academic year, with its two semesters, in one transaction.

    The unique constraint on ``Dsd.academic_year`` is the real guard: the pre-check only gives
    the friendly message, and a request that loses the race with another manager hits the
    constraint and gets the same message (D43).

    Args:
        academic_year: the academic year.
        actor: the user creating it (audited).
        reason: optional reason (D40).

    Returns:
        The new DSD.

    Raises:
        ValidationError: if the academic year already has a DSD.
    """
    if _existing_dsd(academic_year) is not None:
        raise _already_exists(academic_year)
    try:
        with transaction.atomic():
            dsd = Dsd(academic_year=academic_year)
            audited_save(dsd, actor, reason)
            for number in SEMESTER_NUMBERS:
                audited_save(DsdSemester(dsd=dsd, number=number), actor, reason)
    except IntegrityError:
        raise _already_exists(academic_year) from None
    return dsd


@dataclass
class StateChangeResult:
    """What a state change did: the cells it changed and the cells it skipped (D86).

    Attributes:
        changed: ``(semester, coordination)`` pairs whose state changed.
        skipped: pairs where the action did not apply (already in that state, or a move that
            the lifecycle does not allow, such as closing a semester never opened).
    """

    changed: list[tuple[DsdSemester, Coordination]] = field(default_factory=list)
    skipped: list[tuple[DsdSemester, Coordination]] = field(default_factory=list)


def change_state(
    actor,
    action: str,
    semesters: Iterable[DsdSemester],
    coordinations: Iterable[Coordination],
    reason: str = "",
) -> StateChangeResult:
    """Open, close or reopen the given semesters for the given coordinations (D43, D86).

    The selection is expanded into (semester x coordination) cells, locked in a fixed order and
    changed in one transaction, with one audit entry per changed cell. A cell where the action
    does not apply is skipped and reported, never an error. Any PGC manager may do it for any
    coordination: the state belongs to the whole University.

    Args:
        actor: the user acting; must hold ``dsd.semester_state.edit``.
        action: ``"open"``, ``"close"`` or ``"reopen"``.
        semesters: the semesters of the DSD.
        coordinations: the coordinations.
        reason: required to close or reopen, optional to open (D40).

    Returns:
        The changed and the skipped cells.

    Raises:
        PermissionDenied: if the actor may not change states.
        ValidationError: if closing or reopening without a reason.
    """
    registry.require(actor, "dsd.semester_state.edit")
    if needs_reason(action) and not reason.strip():
        raise ValidationError({"reason": _("O motivo é obrigatório.")})
    cells = sorted(
        ((s, c) for s in semesters for c in coordinations),
        key=lambda cell: (cell[0].pk, cell[1].pk),
    )
    result = StateChangeResult()
    with transaction.atomic():
        for semester, coordination in cells:
            row = (
                CoordinationSemester.objects.select_for_update()
                .filter(dsd_semester=semester, coordination=coordination)
                .first()
            )
            new_status = next_state(None if row is None else row.status, action)
            if new_status is None:
                result.skipped.append((semester, coordination))
                continue
            if row is None:
                row = CoordinationSemester(
                    dsd_semester=semester, coordination=coordination, status=new_status
                )
                try:
                    # A savepoint: losing a race on the unique constraint must not poison the
                    # whole transaction; the cell was opened by someone else, so it is skipped.
                    with transaction.atomic():
                        audited_save(row, actor, reason)
                except IntegrityError:
                    result.skipped.append((semester, coordination))
                    continue
            else:
                row.status = new_status
                audited_save(row, actor, reason)
            result.changed.append((semester, coordination))
    return result
