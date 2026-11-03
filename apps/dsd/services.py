"""Use cases of the DSD: create it, change its states and generate the offerings (T2.1-T2.3).

Implements: docs/backlog_fase2.md T2.1, T2.2 and T2.3; D43 (one DSD per academic year, created
by the manager, who also opens, closes and reopens the semesters by coordination), D87.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.academic.models import AcademicYear, ClassGroup, Coordination, Subject
from apps.academic.services import subjects_for
from apps.core.audit import audited_save
from apps.core.permissions import registry

from .lifecycle import CellNotWritable, dsd_write
from .lifecycle_rules import needs_reason, next_state
from .models import (
    CoordinationSemester,
    Dsd,
    DsdSemester,
    Offering,
    OfferingClassGroup,
)

SEMESTER_NUMBERS = (1, 2)
GENERATE = "dsd.offering.generate"


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


@dataclass
class GenerationResult:
    """What generating the offerings did (T2.3, D87).

    Attributes:
        created_offerings: new offerings.
        created_links: new turma links in offerings (new or existing).
        blocked: cells ``(semester, coordination_id)`` skipped because the cell is closed.
        out_of_scope: cells ``(semester, coordination_id)`` skipped because the user does not
            cover that coordination (another Faculty).
        stale_offerings: existing offerings that no turma and plan call for any more.
        stale_links: existing links of turmas that no longer take the offering. Both are kept.
    """

    created_offerings: int = 0
    created_links: int = 0
    blocked: list[tuple[DsdSemester, int]] = field(default_factory=list)
    out_of_scope: list[tuple[DsdSemester, int]] = field(default_factory=list)
    stale_offerings: int = 0
    stale_links: int = 0


def wanted_offerings(dsd_semester: DsdSemester) -> dict[Subject, list[ClassGroup]]:
    """Return which turmas take which subjects in a semester of a DSD (D48, D49, D79).

    A turma takes the subjects of its own plan that are in its curricular year in that academic
    year and in that semester, common ones and those of its track.

    Args:
        dsd_semester: the semester of the DSD.

    Returns:
        The subjects mapped to the turmas that take them, in the order of the turmas.
    """
    year = dsd_semester.dsd.academic_year.start_year
    wanted: dict[Subject, list[ClassGroup]] = {}
    groups = ClassGroup.objects.select_related("course", "study_plan", "track")
    for group in groups:
        curricular_year = group.curricular_year_in(year)
        if curricular_year is None:
            continue
        subjects = subjects_for(group).filter(
            curricular_year=curricular_year, semester=dsd_semester.number
        )
        for subject in subjects.select_related("coordination"):
            wanted.setdefault(subject, []).append(group)
    return wanted


def _ensure(model, lookup: dict, actor, reason: str):
    """Get or create a row, returning ``(row, created)``; a lost race counts as found.

    A savepoint keeps the unique constraint violation from poisoning the transaction, and the
    row the other request created is read back (D86).
    """
    row = model.objects.filter(**lookup).first()
    if row is not None:
        return row, False
    row = model(**lookup)
    try:
        with transaction.atomic():
            audited_save(row, actor, reason)
    except IntegrityError:
        return model.objects.get(**lookup), False
    return row, True


def generate_offerings(
    actor,
    semesters: Iterable[DsdSemester],
    coordination_ids: Iterable[int] | None = None,
    reason: str = "",
) -> GenerationResult:
    """Create the offerings of the semesters from the turmas and their plans (D48, D49).

    It only adds what is missing and never deletes or duplicates, so it can be run again after
    a turma or a subject is added. Each (semester, coordination) cell is written inside
    ``dsd_write``: a closed cell is skipped and reported, a cell not yet opened is allowed
    (the manager prepares before opening, D86), and a coordination the actor does not cover
    (another Faculty, D69) is reported as out of scope.

    Args:
        actor: the user generating; must hold ``dsd.offering.generate`` for the coordinations.
        semesters: the semesters of the DSD.
        coordination_ids: restrict to these coordinations, or ``None`` for all the subjects'.
        reason: optional reason (D40).

    Returns:
        The counts and the skipped cells.

    Raises:
        PermissionDenied: if the actor covers no coordination at all.
    """
    covered = registry.coordination_ids(actor, GENERATE)
    if not covered:
        raise PermissionDenied(f"Not allowed: {GENERATE}")
    only = None if coordination_ids is None else set(coordination_ids)
    result = GenerationResult()
    for semester in sorted(semesters, key=lambda s: s.pk):
        by_coordination: dict[int, dict[Subject, list[ClassGroup]]] = {}
        for subject, groups in wanted_offerings(semester).items():
            by_coordination.setdefault(subject.coordination_id, {})[subject] = groups
        with_offerings = set(
            Offering.objects.filter(dsd_semester=semester).values_list(
                "subject__coordination_id", flat=True
            )
        )
        for coordination_id in sorted(set(by_coordination) | with_offerings):
            if only is not None and coordination_id not in only:
                continue
            if coordination_id not in covered:
                result.out_of_scope.append((semester, coordination_id))
                continue
            wanted = by_coordination.get(coordination_id, {})
            try:
                with dsd_write(actor, GENERATE, semester, coordination_id):
                    _generate_cell(actor, semester, coordination_id, wanted, reason, result)
            except CellNotWritable:
                result.blocked.append((semester, coordination_id))
    return result


def _generate_cell(
    actor,
    semester: DsdSemester,
    coordination_id: int,
    wanted: dict[Subject, list[ClassGroup]],
    reason: str,
    result: GenerationResult,
) -> None:
    """Create the missing offerings and links of one cell and count the stale ones."""
    wanted_ids = {subject.pk for subject in wanted}
    existing = Offering.objects.filter(
        dsd_semester=semester, subject__coordination_id=coordination_id
    )
    result.stale_offerings += existing.exclude(subject_id__in=wanted_ids).count()
    for subject, groups in wanted.items():
        offering, created = _ensure(
            Offering, {"dsd_semester": semester, "subject": subject}, actor, reason
        )
        result.created_offerings += created
        taking = {group.pk for group in groups}
        have = set(offering.class_group_links.values_list("class_group_id", flat=True))
        result.stale_links += len(have - taking)
        for group in groups:
            _, linked = _ensure(
                OfferingClassGroup, {"offering": offering, "class_group": group}, actor, reason
            )
            result.created_links += linked
