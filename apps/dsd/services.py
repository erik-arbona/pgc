"""Use cases of the DSD: create it, change its states and generate the offerings (T2.1-T2.3).

Implements: docs/backlog_fase2.md T2.1 to T3.1; D43 (one DSD per academic year, created
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
from apps.core.audit import audited_delete, audited_save
from apps.core.permissions import registry
from apps.staff.models import Teacher

from .lifecycle import CellNotWritable, dsd_write
from .lifecycle_rules import needs_reason, next_state
from .models import (
    CoordinationSemester,
    Dsd,
    DsdSemester,
    Offering,
    OfferingClassGroup,
    SubGroup,
    TeachingUnit,
    TeachingUnitMember,
)

SEMESTER_NUMBERS = (1, 2)
GENERATE = "dsd.offering.generate"
LEAD_TEACHER = "dsd.offering.lead_teacher.edit"
TEACHING_UNIT_EDIT = "dsd.teaching_unit.edit"
MAX_GROUPS = 20


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
        stale_links: existing links of turmas that no longer take the offering.
        stale_units: existing units whose class type left the subject's loads or whose
            turmas no longer take the offering. All the stale rows are kept.
        created_units: new teaching units, one per turma and class type by default.
    """

    created_offerings: int = 0
    created_links: int = 0
    blocked: list[tuple[DsdSemester, int]] = field(default_factory=list)
    out_of_scope: list[tuple[DsdSemester, int]] = field(default_factory=list)
    stale_offerings: int = 0
    stale_links: int = 0
    stale_units: int = 0
    created_units: int = 0


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
        _ensure_default_units(actor, offering, subject, reason, result)
    result.stale_units += len(_stale_unit_ids(semester, coordination_id, wanted))


def _ensure_default_units(
    actor, offering: Offering, subject: Subject, reason: str, result: GenerationResult
) -> None:
    """Create the missing default units of an offering: one per turma and class type (T3.1).

    A unit and its member are created together in a savepoint, so a member that already exists
    (another request, or an earlier run) leaves no orphan unit behind. The turmas of a merge
    or a group (T3.2, T3.3) are already members of other units and are not touched.
    """
    class_types = list(subject.class_loads.select_related("class_type"))
    have = set(
        TeachingUnitMember.objects.filter(class_group_link__offering=offering).values_list(
            "class_group_link_id", "class_type_id"
        )
    ) | set(
        # A turma divided into groups for a class type has no whole-turma unit for it (T3.2).
        SubGroup.objects.filter(class_group_link__offering=offering).values_list(
            "class_group_link_id", "class_type_id"
        )
    )
    for link in offering.class_group_links.all():
        for load in class_types:
            if (link.pk, load.class_type_id) in have:
                continue
            try:
                with transaction.atomic():
                    unit = TeachingUnit(offering=offering, class_type=load.class_type)
                    audited_save(unit, actor, reason)
                    member = TeachingUnitMember(
                        unit=unit, class_group_link=link, class_type=load.class_type
                    )
                    audited_save(member, actor, reason)
            except IntegrityError:
                continue  # another request created it first
            result.created_units += 1


def _stale_unit_ids(
    semester: DsdSemester, coordination_id: int, wanted: dict[Subject, list[ClassGroup]]
) -> set[int]:
    """Return the ids of the units of a cell that the plan and the turmas no longer call for.

    A unit is stale if its offering is not wanted, its class type left the subject's loads, or
    one of its turmas no longer takes the offering. Nothing is deleted (D87, D89).
    """
    wanted_by_subject = {
        subject.pk: (
            {load.class_type_id for load in subject.class_loads.all()},
            {group.pk for group in groups},
        )
        for subject, groups in wanted.items()
    }
    units = (
        TeachingUnit.objects.filter(
            offering__dsd_semester=semester, offering__subject__coordination_id=coordination_id
        )
        .select_related("offering")
        .prefetch_related("members__class_group_link", "members__subgroup__class_group_link")
    )
    stale: set[int] = set()
    for unit in units:
        entry = wanted_by_subject.get(unit.offering.subject_id)
        if entry is None:
            stale.add(unit.pk)
            continue
        types, groups = entry
        if unit.class_type_id not in types or any(
            member.turma_link.class_group_id not in groups for member in unit.members.all()
        ):
            stale.add(unit.pk)
    return stale


def stale_unit_ids(semester: DsdSemester, coordination_id: int) -> set[int]:
    """Return the ids of the stale units of one cell, computed from the current plans (D89).

    Args:
        semester: the semester of the DSD.
        coordination_id: the coordination that owns the cell.

    Returns:
        The ids of the units to flag as obsolete.
    """
    wanted = {
        subject: groups
        for subject, groups in wanted_offerings(semester).items()
        if subject.coordination_id == coordination_id
    }
    return _stale_unit_ids(semester, coordination_id, wanted)


def set_lead_teacher(
    actor, offering: Offering, teacher: Teacher | None, reason: str = ""
) -> Offering:
    """Set, change or clear the regente of an offering (T2.3b, D87).

    The regente must be an active teacher of the coordination that owns the subject (D69). The
    write goes through ``dsd_write``: open cells accept the coordinator and the manager, cells
    not yet opened only the manager, closed cells nobody (D86). ``offering`` must be the copy
    the user saw, so a stale one is refused by the optimistic lock (D54). The first time needs
    no reason; changing or clearing does (D40).

    Args:
        actor: the user acting.
        offering: the offering as loaded, with the version the user saw.
        teacher: the new regente, or ``None`` to clear it.
        reason: why; required when there already is a regente.

    Returns:
        The offering (unchanged and not written if the teacher is the same).

    Raises:
        PermissionDenied: if the actor does not cover the subject's coordination.
        ValidationError: if the cell is not writable, the teacher is not eligible, the
            version is stale or the reason is missing.
    """
    coordination_id = offering.subject.coordination_id
    with dsd_write(actor, LEAD_TEACHER, offering.dsd_semester, coordination_id):
        if offering.lead_teacher_id == (teacher.pk if teacher else None):
            return offering
        if teacher is not None and (
            not teacher.is_active or teacher.coordination_id != coordination_id
        ):
            raise ValidationError(
                _("O regente tem de ser um docente ativo da coordenação da disciplina.")
            )
        had_one = offering.lead_teacher_id is not None
        if had_one and not reason.strip():
            raise ValidationError({"reason": _("O motivo é obrigatório.")})
        offering.lead_teacher = teacher
        audited_save(offering, actor, reason.strip() or _("Definição do regente"))
    return offering


def unit_versions(link: OfferingClassGroup, class_type) -> dict[int, int]:
    """Return ``{unit id: version}`` of the units that serve a turma for a class type."""
    whole = TeachingUnit.objects.filter(members__class_group_link=link, class_type=class_type)
    grouped = TeachingUnit.objects.filter(
        members__subgroup__class_group_link=link, class_type=class_type
    )
    return {unit.pk: unit.version for unit in whole.union(grouped)}


def _drop_unit(actor, unit: TeachingUnit, reason: str) -> None:
    """Delete a unit with its members and the groups they hold, each with an audit entry.

    Raises:
        ValidationError: if the unit holds more than one member (a merge): separate it first.
    """
    members = list(unit.members.select_related("subgroup"))
    if len(members) > 1:
        raise ValidationError(
            _("A unidade está juntada com outras turmas ou grupos: separe-a primeiro.")
        )
    for member in members:
        subgroup = member.subgroup
        audited_delete(member, actor, reason)
        if subgroup is not None:
            audited_delete(unit, actor, reason)
            audited_delete(subgroup, actor, reason)
            return
    audited_delete(unit, actor, reason)


def _new_unit(actor, offering: Offering, class_type, reason: str, **audience) -> TeachingUnit:
    """Create a unit of a class type with one member (a whole turma or a group)."""
    unit = TeachingUnit(offering=offering, class_type=class_type)
    audited_save(unit, actor, reason)
    audited_save(TeachingUnitMember(unit=unit, class_type=class_type, **audience), actor, reason)
    return unit


def set_group_count(
    actor,
    link: OfferingClassGroup,
    class_type,
    n: int,
    reason: str = "",
    seen_versions: dict[int, int] | None = None,
) -> None:
    """Divide a turma into ``n`` groups for a class type, or change that number (T3.2, D90).

    Each group is one teaching unit of its own, so ``n`` groups count ``n`` times (D70). With
    ``n = 1`` the groups are deleted and the unit of the whole turma is recreated. Going down
    deletes the highest-numbered groups with their units; going up adds the next numbers.
    A turma whose whole-turma unit is merged with others cannot be divided: separate it first.
    The write goes through ``dsd_write`` (D86), under a lock on the turma link. The first
    division needs no reason; changing the number or merging back does (D40); a missing reason on
    the first division is replaced by a default one so that the audit always has one.

    Args:
        actor: the user acting.
        link: the turma of the offering.
        class_type: the class type to divide the turma for.
        n: the number of groups, 1 to 20.
        reason: why; required to change or undo an existing division.
        seen_versions: ``{unit id: version}`` the user saw, to refuse a stale change (D54).

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the cell is not writable, ``n`` is out of range, the version is
            stale, the reason is missing, the turma is merged or the subject has no such type.
    """
    if not 1 <= n <= MAX_GROUPS:
        raise ValidationError(
            _("O número de grupos tem de estar entre 1 e %(max)s.") % {"max": MAX_GROUPS}
        )
    offering = link.offering
    with dsd_write(
        actor, TEACHING_UNIT_EDIT, offering.dsd_semester, offering.subject.coordination_id
    ):
        OfferingClassGroup.objects.select_for_update().get(pk=link.pk)
        if seen_versions is not None and seen_versions != unit_versions(link, class_type):
            raise ValidationError(
                _("Este registo foi alterado por outra pessoa. Recarregue a página.")
            )
        groups = list(SubGroup.objects.filter(class_group_link=link, class_type=class_type))
        whole = (
            TeachingUnitMember.objects.filter(class_group_link=link, class_type=class_type)
            .select_related("unit")
            .first()
        )
        current = len(groups) if groups else (1 if whole else 0)
        if n == current:
            return
        if not offering.subject.class_loads.filter(class_type=class_type).exists():
            raise ValidationError(_("A disciplina não tem este tipo de aula."))
        changing = bool(groups)
        if changing and not reason.strip():
            raise ValidationError({"reason": _("O motivo é obrigatório.")})
        why = reason.strip() or _("Divisão em grupos")
        if not groups and whole is not None:
            _drop_unit(actor, whole.unit, why)
        if n == 1:
            for group in sorted(groups, key=lambda g: -g.number):
                _drop_unit(actor, group.unit_memberships.get().unit, why)
            _new_unit(actor, offering, class_type, why, class_group_link=link)
            return
        for group in sorted(groups, key=lambda g: -g.number):
            if group.number > n:
                _drop_unit(actor, group.unit_memberships.get().unit, why)
        for number in range(1, n + 1):
            if any(g.number == number for g in groups):
                continue
            group = SubGroup(class_group_link=link, class_type=class_type, number=number)
            audited_save(group, actor, why)
            _new_unit(actor, offering, class_type, why, subgroup=group)
