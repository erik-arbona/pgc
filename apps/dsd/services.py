"""Use cases of the DSD: create it, change its states and generate the offerings (T2.1-T2.3).

Implements: docs/backlog_fase2.md T2.1 to T3.4; D43 (one DSD per academic year, created
by the manager, who also opens, closes and reopens the semesters by coordination), D87.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    Coordination,
    CrossCourseSubjectMember,
    Subject,
)
from apps.academic.services import class_group_sizes, effective_group_members, subjects_for
from apps.core.audit import audited_delete, audited_save
from apps.core.permissions import registry
from apps.rooms.models import RoomType
from apps.rooms.services import room_summary
from apps.staff.models import Teacher

from .below_minimum import DECISIONS, REFUSED
from .lifecycle import CellNotWritable, cell_writable, dsd_write
from .lifecycle_rules import needs_reason, next_state
from .load_facts import teacher_loads
from .load_status import LoadStatus
from .models import (
    AcceptedExtraHours,
    BelowMinimumReason,
    BelowMinimumReview,
    CoordinationSemester,
    Dsd,
    DsdSemester,
    Offering,
    OfferingClassGroup,
    OtherActivity,
    SubGroup,
    TeachingUnit,
    TeachingUnitMember,
)
from .sizes import group_students

SEMESTER_NUMBERS = (1, 2)
GENERATE = "dsd.offering.generate"
LEAD_TEACHER = "dsd.offering.lead_teacher.edit"
TEACHING_UNIT_EDIT = "dsd.teaching_unit.edit"
ASSIGNMENT_EDIT = "dsd.assignment.edit"
REVIEW_MINIMUM = "dsd.below_minimum.review"
TEACHER_SHEET_VIEW = "dsd.teacher.view"
COURSE_VIEW = "dsd.course.view"
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

    A unit is stale if one of its members is: the member's offering is not wanted, its class type
    left the member's subject, or its turma no longer takes that subject. Each member is checked
    against its own subject, so a turma of another course merged in (T3.4) is not flagged because
    it is not a turma of the host. A merge between subjects is also stale when it is no longer
    valid: the subjects left the transversal group, the course is no longer indicated, or a plan
    is no longer in force (D47, D48). Nothing is deleted (D87, D89).
    """
    wanted_by_subject = {
        subject.pk: (
            {load.class_type_id for load in subject.class_loads.all()},
            {group.pk for group in groups},
        )
        for subject, groups in wanted.items()
    }
    year = semester.dsd.academic_year.start_year
    units = (
        TeachingUnit.objects.filter(
            offering__dsd_semester=semester, offering__subject__coordination_id=coordination_id
        )
        .select_related("offering__subject__study_plan")
        .prefetch_related(
            "members__class_group_link__offering__subject__study_plan",
            "members__subgroup__class_group_link__offering__subject__study_plan",
        )
    )
    stale: set[int] = set()
    for unit in units:
        subjects = {unit.offering.subject_id: unit.offering.subject}
        is_stale = False
        for member in unit.members.all():
            link = member.turma_link
            subject = link.offering.subject
            subjects[subject.pk] = subject
            entry = wanted_by_subject.get(subject.pk)
            if (
                entry is None
                or unit.class_type_id not in entry[0]
                or link.class_group_id not in entry[1]
            ):
                is_stale = True
        if not is_stale and unit.offering.subject_id not in wanted_by_subject:
            is_stale = True
        if not is_stale and len(subjects) > 1:
            is_stale = _transversal_error(list(subjects.values()), year) is not None
        if is_stale:
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
    # Read the teacher again under a lock: the copy in memory may be older than a teacher given
    # by another request, and ``audited_delete`` does not check versions (D94).
    current = TeachingUnit.objects.select_for_update().filter(pk=unit.pk).first()
    if current is not None and current.teacher_id:
        raise ValidationError(_("A unidade tem docente atribuído: retire-o primeiro."))
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


def _transversal_error(subjects: list[Subject], academic_year: int) -> str | None:
    """Tell why subjects of different courses cannot share a class, or ``None`` if they can.

    They can when every subject belongs to the same cross-course group (D47), still counts in the
    academic year because its plan is in force (D48), and its course is one of the courses the
    manager indicated for the group.

    Args:
        subjects: the subjects whose turmas would share a class; more than one.
        academic_year: start year of the academic year of the DSD.

    Returns:
        The reason in Portuguese, or ``None`` if the merge between them is allowed.
    """
    ids = {subject.pk for subject in subjects}
    groups = {
        membership.subject_id: membership.cross_course_subject
        for membership in CrossCourseSubjectMember.objects.filter(
            subject_id__in=ids
        ).select_related("cross_course_subject")
    }
    if set(groups) != ids:
        return _(
            "As disciplinas não são transversais entre si: só se juntam turmas da mesma disciplina."
        )
    if len({group.pk for group in groups.values()}) != 1:
        return _("As disciplinas não pertencem ao mesmo grupo de disciplinas transversais.")
    group = next(iter(groups.values()))
    if not ids <= {facts.id for facts in effective_group_members(group, academic_year)}:
        return _("Uma das disciplinas já não está em vigor neste ano: o plano mudou.")
    allowed = set(group.allowed_courses.values_list("course_id", flat=True))
    if not {subject.study_plan.course_id for subject in subjects} <= allowed:
        return _("Um dos cursos não está indicado para juntar turmas nesta disciplina.")
    return None


def partner_offerings(offering: Offering) -> list[Offering]:
    """Return the offerings whose turmas could be merged with this offering's (D92).

    They are the offerings of the same DSD semester and coordination whose subject is
    transversal to this one: same group, plan in force, indicated courses. Used to offer the
    units of the other courses on the page.

    Args:
        offering: the offering the page is about.

    Returns:
        The partner offerings, ordered by subject code.
    """
    year = offering.dsd_semester.dsd.academic_year.start_year
    group_ids = CrossCourseSubjectMember.objects.filter(subject=offering.subject).values_list(
        "cross_course_subject_id", flat=True
    )
    candidates = (
        Offering.objects.filter(
            dsd_semester=offering.dsd_semester,
            subject__coordination_id=offering.subject.coordination_id,
            subject__cross_course_memberships__cross_course_subject_id__in=list(group_ids),
        )
        .exclude(pk=offering.pk)
        .select_related("subject__study_plan__course")
        .order_by("subject__code")
        .distinct()
    )
    return [
        candidate
        for candidate in candidates
        if _transversal_error([offering.subject, candidate.subject], year) is None
    ]


def guest_members(offering: Offering) -> list[TeachingUnitMember]:
    """Return the members from this offering that were merged into a unit of another offering.

    Args:
        offering: the offering of the turmas that were merged elsewhere.

    Returns:
        The audience rows, with the unit and its host offering loaded.
    """
    return list(
        TeachingUnitMember.objects.filter(
            Q(class_group_link__offering=offering)
            | Q(subgroup__class_group_link__offering=offering)
        )
        .exclude(unit__offering=offering)
        .select_related(
            "unit__offering__subject__study_plan__course",
            "unit__class_type",
            "class_group_link__class_group",
            "subgroup__class_group_link__class_group",
        )
    )


def _subjects_of(units: Iterable[TeachingUnit]) -> list[Subject]:
    """Return the subjects behind some units: the host offering's and those of their members."""
    units = list(units)
    subjects = {unit.offering.subject_id: unit.offering.subject for unit in units}
    members = TeachingUnitMember.objects.filter(unit__in=units).select_related(
        "class_group_link__offering__subject__study_plan",
        "subgroup__class_group_link__offering__subject__study_plan",
    )
    for member in members:
        subject = member.turma_link.offering.subject
        subjects[subject.pk] = subject
    return list(subjects.values())


def merge_load_differences(units: Iterable[TeachingUnit]) -> dict[str, Decimal]:
    """Return the weekly hours of each subject for the class type, if they differ (Q8, D92).

    Used to warn before merging turmas of subjects that give a different weekly load to the same
    class type; nothing is returned when the subjects agree or there is a single subject.

    Args:
        units: the units that would be merged; they share a class type.

    Returns:
        ``{subject code: weekly hours}``, empty if there is no difference to warn about.
    """
    units = list(units)
    subjects = _subjects_of(units)
    if len(subjects) < 2:
        return {}
    class_type_id = units[0].class_type_id
    hours = {
        subject.code: next(
            (
                load.weekly_hours
                for load in subject.class_loads.all()
                if load.class_type_id == class_type_id
            ),
            Decimal("0"),
        )
        for subject in subjects
    }
    return hours if len(set(hours.values())) > 1 else {}


def _stale_message() -> ValidationError:
    """The error for a change made on top of an older copy of the units (D54)."""
    return ValidationError(_("Este registo foi alterado por outra pessoa. Recarregue a página."))


def merged_students(members: list[TeachingUnitMember]) -> int:
    """Return the students of what a set of members puts together (D90, T3.3).

    A whole turma counts as its size (D81); a group counts as the turma size divided by the
    number of groups of that turma and class type, rounded up.

    Args:
        members: the audience rows.

    Returns:
        The sum.

    Raises:
        ValidationError: if a turma has no enrollment number, so the sum cannot be known.
    """
    academic_year = members[0].unit.offering.dsd_semester.dsd.academic_year
    sizes = class_group_sizes(academic_year)
    total = 0
    for member in members:
        link = member.turma_link
        size = sizes.get(link.class_group_id)
        if size is None:
            raise ValidationError(
                _("Falta a matrícula da turma %(turma)s: sem ela não se sabe a dimensão.")
                % {"turma": link.class_group}
            )
        if member.subgroup_id:
            groups = SubGroup.objects.filter(
                class_group_link=link, class_type_id=member.class_type_id
            ).count()
            total += group_students(size.students, groups)
        else:
            total += size.students
    return total


def merge_units(
    actor,
    units: Iterable[TeachingUnit],
    room_capacity: int,
    room_type: RoomType | None = None,
    reason: str = "",
    seen_versions: dict[int, int] | None = None,
    host: TeachingUnit | None = None,
    accept_load_difference: bool = False,
) -> TeachingUnit:
    """Merge teaching units of one class type into one, also between courses (D23, D91, D92).

    Units of the same offering merge when the rules below hold. Units of different offerings
    merge only between transversal subjects (D47): the subjects must be in the same group, count
    in the academic year (D48), be of indicated courses and of the same coordination (Q8). The
    hours then count under the host's subject, and if the weekly load of the class type differs
    between the subjects the merge needs ``accept_load_difference``.

    The host keeps every member of the merge and the other units are deleted. The merge is only
    allowed if some room of the campus holds the students: the coordinator states the capacity
    (and, optionally, the type) of room asked, which must hold the sum of the students and exist
    in the campus, checked with quantities only (D64); the request is saved on the host.
    Everything is written inside ``dsd_write`` (D86) with the rows locked in a fixed order.

    Args:
        actor: the user acting.
        units: two or more different units of one class type and one DSD semester.
        room_capacity: places of the room asked.
        room_type: type of room asked, or ``None`` for any.
        reason: optional; a default one is recorded (D40).
        seen_versions: ``{unit id: version}`` the user saw, to refuse a stale merge (D54).
        host: the unit that keeps the merge; the first one by default.
        accept_load_difference: the user confirmed a different weekly load between subjects.

    Returns:
        The host unit.

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the units cannot be merged (different semester or class type,
            subjects that are not transversal, an obsolete unit, two groups of one turma, a
            missing enrollment), the cell is not writable, the version is stale, the load
            differs and was not confirmed, or no room of the campus fits.
    """
    unique = list({unit.pk: unit for unit in units}.values())
    if len(unique) < 2:
        raise ValidationError(_("Escolha duas ou mais unidades diferentes para juntar."))
    if len({unit.offering.dsd_semester_id for unit in unique}) != 1:
        raise ValidationError(_("Só se juntam unidades do mesmo semestre."))
    if len({unit.class_type_id for unit in unique}) != 1:
        raise ValidationError(_("Só se juntam unidades do mesmo tipo de aula."))
    host_pk = (host or next((unit for unit in unique if unit.teacher_id), unique[0])).pk
    if host_pk not in {unit.pk for unit in unique}:
        raise ValidationError(_("A unidade que fica tem de ser uma das que se juntam."))
    offering = next(unit for unit in unique if unit.pk == host_pk).offering
    coordination_id = offering.subject.coordination_id
    with dsd_write(actor, TEACHING_UNIT_EDIT, offering.dsd_semester, coordination_id):
        pks = sorted(unit.pk for unit in unique)
        members = list(
            TeachingUnitMember.objects.filter(unit_id__in=pks).select_related(
                "unit__offering__dsd_semester__dsd__academic_year",
                "class_group_link__class_group",
                "subgroup__class_group_link__class_group",
            )
        )
        # Lock the turma links first and the units after, always by id, like set_group_count.
        list(
            OfferingClassGroup.objects.select_for_update()
            .filter(pk__in={member.turma_link.pk for member in members})
            .order_by("pk")
        )
        locked = {
            unit.pk: unit
            for unit in TeachingUnit.objects.select_for_update().filter(pk__in=pks).order_by("pk")
        }
        if len(locked) != len(pks) or (
            seen_versions is not None
            and any(seen_versions.get(pk) != unit.version for pk, unit in locked.items())
        ):
            raise _stale_message()
        if set(pks) & stale_unit_ids(offering.dsd_semester, coordination_id):
            raise ValidationError(
                _("Uma das unidades está obsoleta: já não é pedida pelo plano nem pelas turmas.")
            )
        subjects = _subjects_of(unique)
        if len({subject.coordination_id for subject in subjects}) != 1:
            raise ValidationError(_("Só se juntam unidades da mesma coordenação."))
        if len(subjects) > 1:
            reason_why = _transversal_error(
                subjects, offering.dsd_semester.dsd.academic_year.start_year
            )
            if reason_why is not None:
                raise ValidationError(reason_why)
            differences = merge_load_differences(unique)
            if differences and not accept_load_difference:
                shown = ", ".join(f"{code}: {hours} h" for code, hours in differences.items())
                raise ValidationError(
                    _("Carga semanal diferente entre as disciplinas (%(hours)s): confirme.")
                    % {"hours": shown}
                )
        links = [member.turma_link.pk for member in members if member.subgroup_id]
        if len(links) != len(set(links)):
            raise ValidationError(
                _("Dois grupos da mesma turma não se juntam: altere o número de grupos.")
            )
        students = merged_students(members)
        if room_capacity < students:
            raise ValidationError(
                _("A sala pedida tem de ter lugar para os %(students)s alunos.")
                % {"students": students}
            )
        if not room_summary(room_type.pk if room_type else None, room_capacity):
            raise ValidationError(
                _("Nenhuma sala do campus tem %(capacity)s lugares ou mais: não se pode juntar.")
                % {"capacity": room_capacity}
            )
        teachers = [unit for unit in locked.values() if unit.teacher_id]
        if len(teachers) > 1:
            raise ValidationError(
                _("Mais de uma das unidades tem docente: retire os que sobram antes de juntar.")
            )
        if teachers and teachers[0].pk != host_pk:
            raise ValidationError(
                _("A unidade com docente tem de ser a que fica: o docente não se perde.")
            )
        why = reason.strip() or _("Junção de turmas")
        target = locked[host_pk]
        for member in members:
            if member.unit_id != target.pk:
                member.unit = target
                audited_save(member, actor, why)
        target.room_capacity = room_capacity
        target.room_type = room_type
        audited_save(target, actor, why)
        for unit in locked.values():
            if unit.pk != target.pk:
                audited_delete(unit, actor, why)
    return target


def separate_member(
    actor,
    unit: TeachingUnit,
    member: TeachingUnitMember,
    reason: str,
    seen_version: int | None = None,
) -> TeachingUnit:
    """Take one turma or group out of a merge, into a unit of its own (T3.3, D91).

    The new unit starts without room request; the unit it leaves keeps its own. The last member
    of a unit cannot be separated. Undoing a merge needs a reason (D40).

    Args:
        actor: the user acting.
        unit: the merged unit, as the user saw it.
        member: the member to separate; it must belong to ``unit``.
        reason: why; required.
        seen_version: the version of ``unit`` the user saw (D54).

    Returns:
        The new unit.

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the cell is not writable, the reason is missing, the version is
            stale, the member is not in the unit, or it is the last one.
    """
    if not reason.strip():
        raise ValidationError({"reason": _("O motivo é obrigatório.")})
    offering = unit.offering
    coordination_id = offering.subject.coordination_id
    with dsd_write(actor, TEACHING_UNIT_EDIT, offering.dsd_semester, coordination_id):
        link = member.turma_link
        OfferingClassGroup.objects.select_for_update().get(pk=link.pk)
        try:
            locked = TeachingUnit.objects.select_for_update().get(pk=unit.pk)
        except TeachingUnit.DoesNotExist:
            raise _stale_message() from None
        if seen_version is not None and locked.version != seen_version:
            raise _stale_message()
        current = TeachingUnitMember.objects.filter(unit=locked)
        if not current.filter(pk=member.pk).exists():
            raise ValidationError(_("Este membro já não pertence a esta unidade."))
        if current.count() < 2:
            raise ValidationError(_("A unidade só tem um membro: não há nada a separar."))
        own_offering = member.turma_link.offering
        own_members = [
            other for other in current if other.turma_link.offering_id == locked.offering_id
        ]
        if own_offering.pk == locked.offering_id and len(own_members) == 1:
            raise ValidationError(
                _(
                    "A unidade fica com uma turma da sua disciplina: "
                    "separe primeiro as dos outros cursos."
                )
            )
        why = reason.strip()
        new = TeachingUnit(offering=own_offering, class_type=locked.class_type)
        audited_save(new, actor, why)
        moved = current.get(pk=member.pk)
        moved.unit = new
        audited_save(moved, actor, why)
        audited_save(locked, actor, why)  # bumps the version of the unit the member left
    return new


def unit_students(unit: TeachingUnit) -> int | None:
    """Return the students a unit teaches (a group counts its share of the turma, D90), if known.

    Args:
        unit: the teaching unit.

    Returns:
        The sum for its members, or ``None`` if it has none or a turma has no enrollment number.
    """
    members = list(
        unit.members.select_related(
            "unit__offering__dsd_semester__dsd__academic_year",
            "class_group_link__class_group",
            "subgroup__class_group_link__class_group",
        )
    )
    if not members:
        return None
    try:
        return merged_students(members)
    except ValidationError:
        return None


def room_request_warnings(unit: TeachingUnit, students: int | None) -> list[str]:
    """Return the warnings of the room a unit asks for (T3.5, Q9, D64).

    Computed when shown, from the quantities of rooms, never from one room: no room of the
    campus has the capacity (and type) asked, or the capacity asked is below the students.

    Args:
        unit: the unit and its request.
        students: the students of the unit, or ``None`` if unknown.

    Returns:
        The warnings in Portuguese; empty if there is no request or it is fine.
    """
    if unit.room_capacity is None:
        return []
    warnings: list[str] = []
    if not room_summary(unit.room_type_id, unit.room_capacity):
        kind = f", {unit.room_type.name}" if unit.room_type_id else ""
        warnings.append(
            _("Nenhuma sala do campus serve este pedido (%(capacity)s lugares%(kind)s).")
            % {"capacity": unit.room_capacity, "kind": kind}
        )
    if students is not None and unit.room_capacity < students:
        warnings.append(
            _("A sala pedida (%(capacity)s lugares) não comporta os %(students)s alunos.")
            % {"capacity": unit.room_capacity, "students": students}
        )
    return warnings


def set_room_request(
    actor,
    unit: TeachingUnit,
    room_capacity: int | None,
    room_type: RoomType | None,
    reason: str = "",
    seen_version: int | None = None,
) -> TeachingUnit:
    """Set, change or clear the room a teaching unit asks for (T3.5, Q9, D91).

    The request is a capacity and, optionally, a room type; it is a request, not a booking, and
    it only warns (``room_request_warnings``) when no room fits. Written inside ``dsd_write``
    (D86) with the unit versions the user saw (D54). The first request needs no reason; changing
    or clearing it does (D40).

    Args:
        actor: the user acting.
        unit: the unit.
        room_capacity: places asked, or ``None`` to clear the request.
        room_type: type of room asked, or ``None`` for any; needs a capacity.
        reason: why; required when there already is a request.
        seen_version: the version of the unit the user saw.

    Returns:
        The unit as saved (unchanged and not written if the request is the same).

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the cell is not writable, the capacity is not positive, a type is
            given without capacity, the version is stale or the reason is missing.
    """
    if room_capacity is None and room_type is not None:
        raise ValidationError({"room_capacity": _("Indique a lotação da sala pedida.")})
    if room_capacity is not None and room_capacity < 1:
        raise ValidationError({"room_capacity": _("A lotação tem de ser positiva.")})
    offering = unit.offering
    with dsd_write(
        actor, TEACHING_UNIT_EDIT, offering.dsd_semester, offering.subject.coordination_id
    ):
        try:
            locked = TeachingUnit.objects.select_for_update().get(pk=unit.pk)
        except TeachingUnit.DoesNotExist:
            raise _stale_message() from None
        if seen_version is not None and locked.version != seen_version:
            raise _stale_message()
        new_type = room_type.pk if room_type else None
        if (locked.room_capacity, locked.room_type_id) == (room_capacity, new_type):
            return locked
        if locked.room_capacity is not None and not reason.strip():
            raise ValidationError({"reason": _("O motivo é obrigatório.")})
        locked.room_capacity = room_capacity
        locked.room_type = room_type
        audited_save(locked, actor, reason.strip() or _("Pedido de sala"))
    return locked


def _set_teacher(
    actor,
    unit: TeachingUnit,
    teacher: Teacher | None,
    reason: str,
    seen_version: int | None,
) -> TeachingUnit:
    """Give a unit a teacher, change it or take it off, inside ``dsd_write`` (T5.1, D94).

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the cell is not writable, the version is stale, the teacher is not
            eligible, the unit is obsolete or the reason is missing.
    """
    offering = unit.offering
    coordination_id = offering.subject.coordination_id
    with dsd_write(actor, ASSIGNMENT_EDIT, offering.dsd_semester, coordination_id):
        # Lock the turma links of the unit first and the unit after, like merge and separate, so
        # that a teacher cannot be given while set_group_count is deleting this unit: both hold
        # the link lock, so one waits for the other (D94).
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
        if seen_version is not None and locked.version != seen_version:
            raise _stale_message()
        new_id = teacher.pk if teacher else None
        if locked.teacher_id == new_id:
            return locked
        if teacher is not None:
            if not teacher.is_active or teacher.coordination_id != coordination_id:
                raise ValidationError(
                    _("O docente tem de ser um docente ativo da coordenação da disciplina.")
                )
            if locked.pk in stale_unit_ids(offering.dsd_semester, coordination_id):
                raise ValidationError(
                    _("A unidade está obsoleta: já não é pedida pelo plano nem pelas turmas.")
                )
        if locked.teacher_id is not None and not reason.strip():
            raise ValidationError({"reason": _("O motivo é obrigatório.")})
        locked.teacher = teacher
        audited_save(locked, actor, reason.strip() or _("Atribuição de docente"))
    return locked


def assign_teacher(
    actor,
    unit: TeachingUnit,
    teacher: Teacher,
    reason: str = "",
    seen_version: int | None = None,
) -> TeachingUnit:
    """Give a teaching unit its teacher, or replace the one it has (T5.1, D19, D94).

    A unit has one teacher and nobody shares it. The teacher must be active and of the
    coordination of the unit's subject (D69); an obsolete unit takes none. The first teacher needs
    no reason; replacing one does (D40). The write goes through ``dsd_write`` with the action
    ``dsd.assignment.edit`` (D86) and the version of the unit the user saw (D54).

    Args:
        actor: the user acting.
        unit: the unit.
        teacher: the teacher to give it.
        reason: why; required when the unit already has another teacher.
        seen_version: the version of the unit the user saw.

    Returns:
        The unit as saved (unchanged and not written if the teacher is the same).

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the cell is not writable, the teacher is not eligible, the unit is
            obsolete, the version is stale or the reason is missing.
    """
    return _set_teacher(actor, unit, teacher, reason, seen_version)


def unassign_teacher(
    actor, unit: TeachingUnit, reason: str, seen_version: int | None = None
) -> TeachingUnit:
    """Take the teacher off a teaching unit (T5.1); the reason is required (D40).

    Args:
        actor: the user acting.
        unit: the unit.
        reason: why.
        seen_version: the version of the unit the user saw.

    Returns:
        The unit as saved (unchanged if it had no teacher).

    Raises:
        PermissionDenied: if the actor does not cover the coordination.
        ValidationError: if the cell is not writable, the version is stale or the reason is
            missing.
    """
    return _set_teacher(actor, unit, None, reason, seen_version)


def _locked_activity(activity: OtherActivity, seen_version: int | None) -> OtherActivity:
    """Lock an activity and check that the user saw its current version (D54).

    Raises:
        ValidationError: if the activity is gone or someone saved it after the user loaded it.
    """
    try:
        locked = OtherActivity.objects.select_for_update().get(pk=activity.pk)
    except OtherActivity.DoesNotExist:
        raise _stale_message() from None
    if seen_version is not None and locked.version != seen_version:
        raise _stale_message()
    return locked


def _check_activity_values(description: str, weekly_hours: Decimal | None) -> str:
    """Validate the description and the hours of an activity; return the clean description."""
    errors = {}
    description = description.strip()
    if not description:
        errors["description"] = _("A descrição é obrigatória.")
    if weekly_hours is None or weekly_hours <= 0:
        errors["weekly_hours"] = _("As horas têm de ser maiores que zero.")
    if errors:
        raise ValidationError(errors)
    return description


def add_activity(
    actor,
    teacher: Teacher,
    dsd_semester: DsdSemester,
    kind: str,
    description: str,
    weekly_hours: Decimal,
) -> OtherActivity:
    """Enter an activity of the non-teaching component of a teacher (T5.3, D15, D95).

    The coordinator enters it case by case. The teacher must be active; the write goes through
    ``dsd_write`` for the coordination of the teacher with the action ``dsd.assignment.edit``
    (D69, D86). The hours do not count towards the annual range (D95).

    Args:
        actor: the user acting.
        teacher: the teacher.
        dsd_semester: the semester of the DSD.
        kind: one of ``OtherActivity.Kind``.
        description: what the activity is.
        weekly_hours: the weekly hours, greater than zero.

    Returns:
        The saved activity.

    Raises:
        PermissionDenied: if the actor does not cover the coordination of the teacher.
        ValidationError: if the cell is not writable, the teacher is inactive, the kind is not
            valid, or the description or the hours are not valid.
    """
    with dsd_write(actor, ASSIGNMENT_EDIT, dsd_semester, teacher.coordination_id):
        # The caller's copy may be old: read the teacher again under a lock, so that a teacher who
        # moved or was deactivated meanwhile cannot get an activity in the cell of the old
        # coordination (the cell above was chosen from the copy).
        try:
            current = Teacher.objects.select_for_update().get(pk=teacher.pk)
        except Teacher.DoesNotExist:
            raise _stale_message() from None
        if current.coordination_id != teacher.coordination_id:
            raise _stale_message()
        if not current.is_active:
            raise ValidationError(_("O docente tem de estar ativo."))
        if kind not in OtherActivity.Kind.values:
            raise ValidationError({"kind": _("Tipo de atividade inválido.")})
        description = _check_activity_values(description, weekly_hours)
        activity = OtherActivity(
            dsd_semester=dsd_semester,
            teacher=current,
            coordination_id=current.coordination_id,
            kind=kind,
            description=description,
            weekly_hours=weekly_hours,
        )
        audited_save(activity, actor, _("Nova atividade"))
    return activity


def edit_activity(
    actor,
    activity: OtherActivity,
    kind: str,
    description: str,
    weekly_hours: Decimal,
    reason: str,
    seen_version: int | None = None,
) -> OtherActivity:
    """Change the type, the description or the hours of an activity (T5.3, D40, D54).

    The cell is that of the activity (its stored coordination), so a teacher who changed
    coordination keeps the activities where they were entered.

    Args:
        actor: the user acting.
        activity: the activity.
        kind: one of ``OtherActivity.Kind``.
        description: what the activity is.
        weekly_hours: the weekly hours, greater than zero.
        reason: why; required.
        seen_version: the version the user saw.

    Returns:
        The activity as saved.

    Raises:
        PermissionDenied: if the actor does not cover the coordination of the activity.
        ValidationError: if the cell is not writable, the version is stale, the reason is
            missing or a value is not valid.
    """
    with dsd_write(actor, ASSIGNMENT_EDIT, activity.dsd_semester, activity.coordination_id):
        locked = _locked_activity(activity, seen_version)
        if not reason.strip():
            raise ValidationError({"reason": _("O motivo é obrigatório.")})
        if kind not in OtherActivity.Kind.values:
            raise ValidationError({"kind": _("Tipo de atividade inválido.")})
        locked.kind = kind
        locked.description = _check_activity_values(description, weekly_hours)
        locked.weekly_hours = weekly_hours
        audited_save(locked, actor, reason.strip())
    return locked


def remove_activity(
    actor, activity: OtherActivity, reason: str, seen_version: int | None = None
) -> None:
    """Remove an activity, with a reason, leaving the deletion in the audit (T5.3, D40).

    Args:
        actor: the user acting.
        activity: the activity.
        reason: why; required.
        seen_version: the version the user saw.

    Raises:
        PermissionDenied: if the actor does not cover the coordination of the activity.
        ValidationError: if the cell is not writable, the version is stale or the reason is
            missing.
    """
    with dsd_write(actor, ASSIGNMENT_EDIT, activity.dsd_semester, activity.coordination_id):
        locked = _locked_activity(activity, seen_version)
        if not reason.strip():
            raise ValidationError({"reason": _("O motivo é obrigatório.")})
        audited_delete(locked, actor, reason.strip())


@contextmanager
def _year_write(actor, dsd: Dsd, coordination_id: int) -> Iterator[DsdSemester]:
    """Write data that belongs to the whole year through the cell of one of its semesters (D96).

    The DSD has two semesters, each with its own state per coordination. A record of the year
    is writable if any of the two cells is: the later one is tried first. If neither is, the
    error of the later one is raised (closed, not opened, or no permission).

    Args:
        actor: the user writing.
        dsd: the DSD.
        coordination_id: the coordination that owns the data.

    Yields:
        The semester whose cell is open for the write.
    """
    semesters = list(dsd.semesters.order_by("-number"))
    chosen = next(
        (s for s in semesters if cell_writable(actor, ASSIGNMENT_EDIT, s, coordination_id)),
        semesters[0],
    )
    with dsd_write(actor, ASSIGNMENT_EDIT, chosen, coordination_id):
        yield chosen


def set_accepted_extra(
    actor,
    teacher: Teacher,
    dsd: Dsd,
    hours: Decimal,
    reason: str = "",
    seen_version: int | None = None,
) -> AcceptedExtraHours:
    """Record the extra hours a teacher accepted in a DSD, or change them (T5.4, D13, D96).

    One record per teacher and year. The first time needs no reason; changing it does (D40) and
    needs the version the user saw (D54). The write goes through the cell of any writable
    semester of the year (``_year_write``) with ``dsd.assignment.edit``.

    Args:
        actor: the user acting.
        teacher: the teacher.
        dsd: the DSD.
        hours: the accepted hours, greater than zero.
        reason: why; required when a record already exists.
        seen_version: the version of the existing record the user saw.

    Returns:
        The record as saved.

    Raises:
        PermissionDenied: if the actor does not cover the coordination of the teacher.
        ValidationError: if no cell of the year is writable, the teacher is inactive or moved,
            the hours are not valid, the version is stale or the reason is missing.
    """
    with _year_write(actor, dsd, teacher.coordination_id) as semester:
        # Lock the teacher: it serializes two creators and shows a move that happened after the
        # caller loaded them (the cell above was chosen from the caller's copy).
        try:
            current = Teacher.objects.select_for_update().get(pk=teacher.pk)
        except Teacher.DoesNotExist:
            raise _stale_message() from None
        if current.coordination_id != teacher.coordination_id:
            raise _stale_message()
        if not current.is_active:
            raise ValidationError(_("O docente tem de estar ativo."))
        if hours is None or hours <= 0:
            raise ValidationError({"hours": _("As horas têm de ser maiores que zero.")})
        record = (
            AcceptedExtraHours.objects.select_for_update().filter(dsd=dsd, teacher=current).first()
        )
        if record is None:
            record = AcceptedExtraHours(
                dsd=dsd,
                teacher=current,
                dsd_semester=semester,
                coordination_id=current.coordination_id,
                hours=hours,
            )
            audited_save(record, actor, _("Horas extra aceites"))
            return record
        # A form loaded before the record existed carries no version: that is stale too.
        if seen_version is None or record.version != seen_version:
            raise _stale_message()
        if not reason.strip():
            raise ValidationError({"reason": _("O motivo é obrigatório.")})
        record.hours = hours
        record.dsd_semester = semester
        record.coordination_id = current.coordination_id
        audited_save(record, actor, reason.strip())
    return record


def clear_accepted_extra(
    actor, record: AcceptedExtraHours, reason: str, seen_version: int | None = None
) -> None:
    """Remove the record of accepted extra hours, with a reason (T5.4, D13, D40).

    Args:
        actor: the user acting.
        record: the record.
        reason: why; required.
        seen_version: the version the user saw.

    Raises:
        PermissionDenied: if the actor does not cover the coordination of the record.
        ValidationError: if no cell of the year is writable, the version is stale or the reason
            is missing.
    """
    # The cell is the teacher's coordination now, read from the database, not the caller's copy.
    coordination_id = Teacher.objects.values_list("coordination_id", flat=True).get(
        pk=record.teacher_id
    )
    with _year_write(actor, record.dsd, coordination_id) as semester:
        # Same lock order as set_accepted_extra (teacher, then record), so the two cannot
        # interleave; and the teacher may have moved since the caller loaded the record.
        current = Teacher.objects.select_for_update().get(pk=record.teacher_id)
        if current.coordination_id != coordination_id:
            raise _stale_message()
        try:
            locked = AcceptedExtraHours.objects.select_for_update().get(pk=record.pk)
        except AcceptedExtraHours.DoesNotExist:
            raise _stale_message() from None
        if seen_version is not None and locked.version != seen_version:
            raise _stale_message()
        if not reason.strip():
            raise ValidationError({"reason": _("O motivo é obrigatório.")})
        locked._write_cell = (semester.pk, coordination_id)  # for the guard only
        audited_delete(locked, actor, reason.strip())


def set_minimum_reason(
    actor,
    teacher: Teacher,
    dsd: Dsd,
    text: str,
    seen_version: int | None = None,
) -> BelowMinimumReason:
    """Register the reason for a teacher whose load is below the minimum, or change it (T5.5, D16).

    Only a teacher below the minimum of their range takes a reason. One record per teacher and
    year, written through the cell of any writable semester of the year (D96). The first time needs
    no version; changing the text needs the version the user saw (D54) and sends the case back to
    the Executive Board, because a review belongs to one version of the text (D97).

    Args:
        actor: the user acting.
        teacher: the teacher.
        dsd: the DSD.
        text: why the load is below the minimum.
        seen_version: the version of the existing record the user saw.

    Returns:
        The record as saved.

    Raises:
        PermissionDenied: if the actor does not cover the coordination of the teacher.
        ValidationError: if no cell of the year is writable, the teacher is inactive, moved or
            not below the minimum, the text is empty or the version is stale.
    """
    with _year_write(actor, dsd, teacher.coordination_id) as semester:
        try:
            current = Teacher.objects.select_for_update().get(pk=teacher.pk)
        except Teacher.DoesNotExist:
            raise _stale_message() from None
        if current.coordination_id != teacher.coordination_id:
            raise _stale_message()
        if not current.is_active:
            raise ValidationError(_("O docente tem de estar ativo."))
        text = text.strip()
        if not text:
            raise ValidationError({"text": _("O motivo é obrigatório.")})
        status = teacher_loads(dsd, [current])[current.pk].assessment.status
        if status != LoadStatus.BELOW_MINIMUM:
            raise ValidationError(_("O docente não está abaixo da carga mínima."))
        record = (
            BelowMinimumReason.objects.select_for_update().filter(dsd=dsd, teacher=current).first()
        )
        if record is None:
            record = BelowMinimumReason(
                dsd=dsd,
                teacher=current,
                dsd_semester=semester,
                coordination_id=current.coordination_id,
                text=text,
            )
            audited_save(record, actor, _("Motivo abaixo da mínima"))
            return record
        if seen_version is None or record.version != seen_version:
            raise _stale_message()
        record.text = text
        record.dsd_semester = semester
        record.coordination_id = current.coordination_id
        audited_save(record, actor, _("Motivo abaixo da mínima alterado"))
    return record


def review_minimum_reason(
    actor,
    reason: BelowMinimumReason,
    decision: str,
    comment: str,
    seen_version: int | None,
) -> BelowMinimumReview:
    """Accept or refuse the reason for a load below the minimum, as the Executive Board (T5.5).

    The board of the Faculty of the teacher decides (``dsd.below_minimum.review``, D69). It
    reviews data without changing any DSD cell, so a closed cell does not stop it (D97). The
    decision is of the version of the text the board saw: if the coordinator changed it meanwhile
    the review is stale (D54). A refusal needs a comment; deciding again replaces the decision,
    both audited.

    Args:
        actor: the user acting.
        reason: the reason.
        decision: ``"accepted"`` or ``"refused"``.
        comment: why it was refused (required then).
        seen_version: the version of the text the user saw.

    Returns:
        The review as saved.

    Raises:
        PermissionDenied: if the actor is not the board of the Faculty of the teacher.
        ValidationError: if the decision is not valid, a refusal has no comment or the version is
            stale.
    """
    coordination_id = Teacher.objects.values_list("coordination_id", flat=True).get(
        pk=reason.teacher_id
    )
    registry.require_on_coordination(actor, REVIEW_MINIMUM, coordination_id)
    if decision not in DECISIONS:
        raise ValidationError({"decision": _("Decisão inválida.")})
    comment = comment.strip()
    if decision == REFUSED and not comment:
        raise ValidationError({"comment": _("Indique porque recusa o motivo.")})
    with transaction.atomic():
        try:
            locked = BelowMinimumReason.objects.select_for_update().get(pk=reason.pk)
        except BelowMinimumReason.DoesNotExist:
            raise _stale_message() from None
        if seen_version is None or locked.version != seen_version:
            raise _stale_message()
        review = BelowMinimumReview.objects.filter(reason=locked).first() or BelowMinimumReview(
            reason=locked
        )
        review.reviewed_version = locked.version
        review.decision = decision
        review.comment = comment
        review.reviewed_by = actor
        audited_save(review, actor, comment or _("Motivo aceite"))
    return review
