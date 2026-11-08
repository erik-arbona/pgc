"""Use cases of the tender proposals: propose, decide, invite, fill (block 5, entrega 1).

Implements: docs/especificacao/05_dsd_regras.md – tender proposals; D17, D46, D86, D97, D105.

The coordinator proposes and withdraws inside ``dsd_write`` (the cell rules of D86 apply); the
Executive Board decides with the scoped action ``dsd.tender.decide`` and without a cell, like the
review of a reason below the minimum (D97); the PGC manager registers the teacher obtained by the
tender with ``dsd.tender.fill``. The state machine is in ``tender_rules``. A unit with an open
proposal takes no other teacher (``services._set_teacher`` checks it).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.audit import audited_save
from apps.core.permissions import registry
from apps.staff.models import Teacher

from .lifecycle import dsd_write
from .models import (
    OfferingClassGroup,
    TeachingUnit,
    TeachingUnitMember,
    TenderEvent,
    TenderProposal,
)
from .services import (
    ASSIGNMENT_EDIT,
    TENDER_DECIDE,
    TENDER_FILL,
    _set_teacher,
    _stale_message,
    stale_unit_ids,
)
from .tender_rules import OPEN_STATES, TenderAction, TenderState, needs_comment, next_state


def _coordination_of(unit: TeachingUnit) -> int:
    """The coordination that owns a unit: that of its subject (D69)."""
    return unit.offering.subject.coordination_id


def _check_collaborator(teacher: Teacher, coordination_id: int) -> None:
    """Require an active habitual collaborator of the coordination (D46, D08).

    Raises:
        ValidationError: if the teacher is not one.
    """
    if (
        not teacher.is_active
        or teacher.teacher_type != Teacher.Type.HABITUAL_COLLABORATOR
        or teacher.coordination_id != coordination_id
    ):
        raise ValidationError(
            _("Tem de ser um colaborador habitual ativo da coordenação da disciplina.")
        )


def _check_text(reason_kind: str, justification: str) -> str:
    """Validate the kind and the justification of a proposal; return the clean justification."""
    if reason_kind not in TenderProposal.ReasonKind.values:
        raise ValidationError({"reason_kind": _("Motivo inválido.")})
    text = justification.strip()
    if not text:
        raise ValidationError({"justification": _("A justificação é obrigatória.")})
    return text


def _record(proposal: TenderProposal, from_state: str, actor, comment: str = "") -> None:
    """Write a step in the history of a proposal."""
    TenderEvent.objects.create(
        proposal=proposal,
        from_state=from_state,
        to_state=proposal.state,
        actor=actor,
        comment=comment.strip(),
    )


def _locked(proposal: TenderProposal, seen_version: int | None) -> TenderProposal:
    """Lock a proposal and check the version the user saw (D54).

    Raises:
        ValidationError: if it is gone or was changed by someone else.
    """
    try:
        locked = TenderProposal.objects.select_for_update().get(pk=proposal.pk)
    except TenderProposal.DoesNotExist:
        raise _stale_message() from None
    if seen_version is None or locked.version != seen_version:
        raise _stale_message()
    return locked


def _move(proposal: TenderProposal, action: TenderAction, actor, comment: str = "") -> None:
    """Apply an action to a locked proposal: new state, saved, audited, in the history.

    Raises:
        ValidationError: if the action cannot be done from the current state.
    """
    before = proposal.state
    try:
        proposal.state = next_state(TenderState(before), action).value
    except ValueError as error:
        raise ValidationError(str(error)) from None
    audited_save(proposal, actor, comment.strip() or action.value)
    _record(proposal, before, actor, comment)


def propose_tender(
    actor,
    unit: TeachingUnit,
    reason_kind: str,
    justification: str,
    suggested_teacher: Teacher | None = None,
) -> TenderProposal:
    """Propose a unit without a teacher to tender, with a justification (D17).

    Args:
        actor: the user acting (the coordinator, or the manager before the cell is opened).
        unit: the unit; it must have no teacher, not be obsolete and have no open proposal.
        reason_kind: one of ``TenderProposal.ReasonKind``.
        justification: why no teacher of the coordination can take it; required.
        suggested_teacher: an active habitual collaborator of the coordination, if any (D46).

    Returns:
        The proposal, waiting for the board.

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the cell is not writable or the unit, the kind, the justification or
            the suggested collaborator are not valid.
    """
    offering = unit.offering
    coordination_id = offering.subject.coordination_id
    text = _check_text(reason_kind, justification)
    with dsd_write(actor, ASSIGNMENT_EDIT, offering.dsd_semester, coordination_id):
        # Lock the turma links and then the unit, as the other unit writers do, so that this does
        # not run while a turma is divided and the unit deleted.
        members = TeachingUnitMember.objects.filter(unit_id=unit.pk).select_related(
            "class_group_link", "subgroup__class_group_link"
        )
        list(
            OfferingClassGroup.objects.select_for_update()
            .filter(pk__in={member.turma_link.pk for member in members})
            .order_by("pk")
        )
        try:
            locked = TeachingUnit.objects.select_for_update().get(pk=unit.pk)
        except TeachingUnit.DoesNotExist:
            raise _stale_message() from None
        if locked.teacher_id is not None:
            raise ValidationError(_("A unidade já tem docente: não há nada a propor."))
        if locked.pk in stale_unit_ids(offering.dsd_semester, coordination_id):
            raise ValidationError(
                _("A unidade está obsoleta: já não é pedida pelo plano nem pelas turmas.")
            )
        if TenderProposal.objects.filter(unit=locked, state__in=OPEN_STATES).exists():
            raise ValidationError(_("A unidade já tem uma proposta de concurso aberta."))
        if suggested_teacher is not None:
            _check_collaborator(suggested_teacher, coordination_id)
        proposal = TenderProposal(
            unit=locked,
            reason_kind=reason_kind,
            justification=text,
            suggested_teacher=suggested_teacher,
        )
        audited_save(proposal, actor, _("Proposta de concurso"))
        _record(proposal, "", actor, text)
    return proposal


def resubmit_tender(
    actor,
    proposal: TenderProposal,
    reason_kind: str,
    justification: str,
    suggested_teacher: Teacher | None,
    seen_version: int | None,
) -> TenderProposal:
    """Treat a refused proposal again: a new justification, and it goes back to the board (05).

    Args:
        actor: the coordinator.
        proposal: the refused proposal.
        reason_kind: the usual reason.
        justification: the new justification; required.
        suggested_teacher: the suggested collaborator, or ``None``.
        seen_version: the version the user saw (D54).

    Returns:
        The proposal, waiting for the board again.

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the cell is not writable, the proposal is not refused, the version
            is stale or the text or the collaborator are not valid.
    """
    unit = proposal.unit
    text = _check_text(reason_kind, justification)
    with dsd_write(actor, ASSIGNMENT_EDIT, unit.offering.dsd_semester, _coordination_of(unit)):
        locked = _locked(proposal, seen_version)
        if suggested_teacher is not None:
            _check_collaborator(suggested_teacher, _coordination_of(unit))
        if locked.unit_id in stale_unit_ids(unit.offering.dsd_semester, _coordination_of(unit)):
            raise ValidationError(
                _("A unidade está obsoleta: já não é pedida pelo plano nem pelas turmas.")
            )
        locked.reason_kind = reason_kind
        locked.justification = text
        locked.suggested_teacher = suggested_teacher
        locked.board_comment = ""  # the history keeps what the board said
        _move(locked, TenderAction.RESUBMIT, actor, text)
    return locked


def withdraw_tender(
    actor, proposal: TenderProposal, reason: str, seen_version: int | None
) -> TenderProposal:
    """Withdraw a proposal before the board has invited anybody (D40: a reason is required).

    Args:
        actor: the coordinator.
        proposal: the proposal.
        reason: why; required.
        seen_version: the version the user saw (D54).

    Returns:
        The withdrawn proposal.

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the cell is not writable, the reason is missing, the version is
            stale or the proposal can no longer be withdrawn.
    """
    unit = proposal.unit
    with dsd_write(actor, ASSIGNMENT_EDIT, unit.offering.dsd_semester, _coordination_of(unit)):
        locked = _locked(proposal, seen_version)
        if not reason.strip():
            raise ValidationError({"reason": _("O motivo é obrigatório.")})
        _move(locked, TenderAction.WITHDRAW, actor, reason)
    return locked


_BOARD_ACTIONS = {
    TenderAction.REFUSE,
    TenderAction.APPROVE,
    TenderAction.INVITE,
    TenderAction.SEND_TO_TENDER,
    TenderAction.ACCEPT_INVITATION,
    TenderAction.DECLINE_INVITATION,
    TenderAction.CANCEL,
}


def decide_tender(
    actor,
    proposal: TenderProposal,
    action: TenderAction | str,
    comment: str = "",
    teacher: Teacher | None = None,
    seen_version: int | None = None,
) -> TenderProposal:
    """Decide as the Executive Board: refuse, approve, invite, launch the tender, record the answer.

    The board of the Faculty of the coordination decides (``dsd.tender.decide``, D69). It does not
    write the distribution, so a closed cell does not stop it (D97).

    Args:
        actor: the Executive Board user.
        proposal: the proposal.
        action: refuse, approve, invite, send_to_tender, accept_invitation, decline_invitation
            or cancel (closes a case that cannot go on, from any open state).
        comment: what the board says; required to refuse and to cancel.
        teacher: the collaborator to invite (required to invite).
        seen_version: the version the user saw (D54).

    Returns:
        The proposal after the decision.

    Raises:
        PermissionDenied: if the actor is not the board of the Faculty of the coordination.
        ValidationError: if the action is not valid from the current state, the comment or the
            collaborator are missing or not valid, or the version is stale.
    """
    action = TenderAction(action)
    if action not in _BOARD_ACTIONS:
        raise ValidationError(_("Ação inválida."))
    coordination_id = _coordination_of(proposal.unit)
    registry.require_on_coordination(actor, TENDER_DECIDE, coordination_id)
    if needs_comment(action) and not comment.strip():
        raise ValidationError({"comment": _("Indique o que falta na proposta.")})
    with transaction.atomic():
        locked = _locked(proposal, seen_version)
        if action == TenderAction.INVITE:
            if teacher is None:
                raise ValidationError({"teacher": _("Escolha o colaborador a convidar.")})
            _check_collaborator(teacher, coordination_id)
            locked.invited_teacher = teacher
        if action == TenderAction.REFUSE:
            locked.board_comment = comment.strip()
        if action == TenderAction.DECLINE_INVITATION:
            locked.invited_teacher = None  # the history keeps who it was
        _move(locked, action, actor, comment)
    return locked


def fill_tender(
    actor, proposal: TenderProposal, teacher: Teacher, seen_version: int | None
) -> TenderProposal:
    """Register the teacher the tender obtained and give them the unit (the PGC manager).

    Args:
        actor: the PGC manager (``dsd.tender.fill``).
        proposal: a proposal in the state «A concurso».
        teacher: an active teacher of the coordination of the subject (D94).
        seen_version: the version the user saw (D54).

    Returns:
        The filled proposal.

    Raises:
        PermissionDenied: if the actor is not the manager of the Faculty of the coordination.
        ValidationError: if the proposal is not in tender, the version is stale or the teacher is
            not eligible for the unit.
    """
    unit = proposal.unit
    registry.require_on_coordination(actor, TENDER_FILL, _coordination_of(unit))
    # ``_set_teacher`` takes the locks in the order of every unit writer (turma links, unit,
    # proposal) and checks, under them, that the proposal is in tender and has the version seen.
    _set_teacher(actor, unit, teacher, "", None, tender=proposal, tender_version=seen_version)
    proposal.refresh_from_db()
    return proposal
