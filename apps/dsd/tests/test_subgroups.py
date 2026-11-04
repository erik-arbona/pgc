"""Tests for splitting a turma into N groups by class type (T3.2a).

Implements: docs/backlog_fase2.md T3.2; D19 (one teacher per class type of each turma or group),
D70 (N groups count N times), D86 (state of the cell), D89 (units). A group is one more teaching
unit; its audience can later hold groups of several turmas (merges, T3.3 and T3.4), so the unit
audience may hold whole turmas or groups.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
    SubjectClassLoad,
)
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.dsd.models import (
    OfferingClassGroup,
    SubGroup,
    TeachingUnit,
    TeachingUnitMember,
)
from apps.dsd.services import change_state, create_dsd, generate_offerings, set_group_count

pytestmark = pytest.mark.django_db


def user_with(django_user_model, profile, kind, scope_id, username):
    """A user with one role."""
    user = django_user_model.objects.create_user(username=username, password="x")
    RoleAssignment.objects.create(user=user, profile=profile, scope_kind=kind, scope_id=scope_id)
    return user


@pytest.fixture
def world(django_user_model):
    """A DSD of 2026 with turma A and a subject with T (2 h) and P (3 h), generated."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    other = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2025, 2026)}
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="EIC", level="bachelor"),
        academic_year=years[2023],
    )
    manager = user_with(django_user_model, Profile.PGC_MANAGER, ScopeKind.FACULTY, faculty.pk, "m")
    turma = ClassGroup.objects.create(
        course=plan.course, intake_year=years[2026], study_plan=plan, label="A"
    )
    subject = Subject.objects.create(
        study_plan=plan,
        code="A1",
        name="Disciplina A1",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=coordination,
        semester_hours=Decimal("75"),
    )
    for code, hours in (("T", "2"), ("P", "3")):
        SubjectClassLoad.objects.create(
            subject=subject, class_type=ClassType.objects.get(code=code), weekly_hours=hours
        )
    dsd = create_dsd(years[2026], manager)
    semester = dsd.semesters.get(number=1)
    generate_offerings(manager, [semester])
    return {
        "manager": manager,
        "coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, coordination.pk, "c"
        ),
        "other_coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, other.pk, "o"
        ),
        "teacher": user_with(django_user_model, Profile.TEACHER, ScopeKind.NONE, None, "t"),
        "semester": semester,
        "coordination": coordination,
        "turma": turma,
        "subject": subject,
        "plan": plan,
        "years": years,
        "link": OfferingClassGroup.objects.get(),
        "T": ClassType.objects.get(code="T"),
        "P": ClassType.objects.get(code="P"),
    }


def open_cell(world):
    """Open the semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def split(world, who, n, class_type="P", **kwargs):
    """Set the number of groups of the turma for a class type."""
    return set_group_count(world[who], world["link"], world[class_type], n, **kwargs)


def units(world, class_type="P"):
    """The units of the turma for a class type."""
    return TeachingUnit.objects.filter(
        offering=world["link"].offering, class_type=world[class_type]
    )


def numbers(world, class_type="P"):
    """The group numbers of the turma for a class type, ascending."""
    return list(
        SubGroup.objects.filter(
            class_group_link=world["link"], class_type=world[class_type]
        ).values_list("number", flat=True)
    )


# --- the models --------------------------------------------------------------------------------


def test_a_group_number_is_unique_per_turma_and_class_type(world):
    """Two groups cannot share a number in the same turma and type."""
    SubGroup.objects.bulk_create(
        [SubGroup(class_group_link=world["link"], class_type=world["P"], number=1)]
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        SubGroup.objects.bulk_create(
            [SubGroup(class_group_link=world["link"], class_type=world["P"], number=1)]
        )


def test_a_group_number_starts_at_one(world):
    """Group 0 does not exist."""
    with pytest.raises(IntegrityError), transaction.atomic():
        SubGroup.objects.bulk_create(
            [SubGroup(class_group_link=world["link"], class_type=world["P"], number=0)]
        )


def test_a_group_cannot_be_saved_outside_the_guard(world):
    """DSD data is written inside ``dsd_write`` only."""
    with pytest.raises(ImproperlyConfigured):
        SubGroup(class_group_link=world["link"], class_type=world["P"], number=1).save()


def test_a_member_is_a_whole_turma_or_a_group_never_both_or_neither(world):
    """The audience row points at exactly one of the two (database check)."""
    unit = units(world, "P").get()
    group = SubGroup.objects.bulk_create(
        [SubGroup(class_group_link=world["link"], class_type=world["P"], number=1)]
    )[0]
    for link, subgroup in ((world["link"], group), (None, None)):
        with pytest.raises(IntegrityError), transaction.atomic():
            TeachingUnitMember.objects.bulk_create(
                [
                    TeachingUnitMember(
                        unit=unit,
                        class_group_link=link,
                        subgroup=subgroup,
                        class_type=world["P"],
                    )
                ]
            )


def test_a_group_belongs_to_at_most_one_unit(world):
    """Two units cannot hold the same group (database unique)."""
    group = SubGroup.objects.bulk_create(
        [SubGroup(class_group_link=world["link"], class_type=world["P"], number=1)]
    )[0]
    first, second = TeachingUnit.objects.bulk_create(
        [TeachingUnit(offering=world["link"].offering, class_type=world["P"]) for _ in range(2)]
    )
    TeachingUnitMember.objects.bulk_create(
        [TeachingUnitMember(unit=first, subgroup=group, class_type=world["P"])]
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        TeachingUnitMember.objects.bulk_create(
            [TeachingUnitMember(unit=second, subgroup=group, class_type=world["P"])]
        )


def test_the_group_class_type_must_match_the_unit(world):
    """A group of type T cannot be a member of a unit of type P."""
    unit = units(world, "P").get()
    group = SubGroup.objects.bulk_create(
        [SubGroup(class_group_link=world["link"], class_type=world["T"], number=1)]
    )[0]
    with pytest.raises(ValidationError):
        TeachingUnitMember(unit=unit, subgroup=group, class_type=world["P"]).clean()


# --- splitting, growing, shrinking, merging back -----------------------------------------------


def test_splitting_replaces_the_whole_turma_unit_by_one_unit_per_group(world):
    """1 unit of the whole turma becomes 3 units, one per group, numbered 1 to 3."""
    open_cell(world)
    split(world, "coordinator", 3)
    assert numbers(world) == [1, 2, 3] and units(world).count() == 3
    for unit in units(world):
        member = unit.members.get()
        assert member.class_group_link is None and member.subgroup.class_type == world["P"]
    assert not TeachingUnitMember.objects.filter(
        class_group_link=world["link"], class_type=world["P"]
    ).exists()


def test_the_other_class_types_are_not_touched(world):
    """Splitting P leaves the whole-turma unit of T as it was."""
    open_cell(world)
    split(world, "coordinator", 2)
    assert units(world, "T").count() == 1
    assert units(world, "T").get().members.get().class_group_link == world["link"]


def test_growing_adds_groups_from_the_next_number(world):
    """From 2 to 4 groups: groups 3 and 4 are added, 1 and 2 stay as they were."""
    open_cell(world)
    split(world, "coordinator", 2)
    kept = set(units(world).values_list("pk", flat=True))
    split(world, "coordinator", 4, reason="more labs")
    assert numbers(world) == [1, 2, 3, 4] and kept <= set(units(world).values_list("pk", flat=True))


def test_shrinking_deletes_the_highest_groups_and_their_units(world):
    """From 4 to 2 groups: groups 3 and 4 and their units are deleted."""
    open_cell(world)
    split(world, "coordinator", 4)
    split(world, "coordinator", 2, reason="fewer labs")
    assert numbers(world) == [1, 2] and units(world).count() == 2


def test_one_group_goes_back_to_the_whole_turma(world):
    """N = 1 deletes the groups and recreates the unit of the whole turma."""
    open_cell(world)
    split(world, "coordinator", 3)
    split(world, "coordinator", 1, reason="back to one class")
    assert numbers(world) == [] and units(world).count() == 1
    assert units(world).get().members.get().class_group_link == world["link"]


def test_the_same_number_writes_nothing(world):
    """No change: no version bump and no audit entry."""
    open_cell(world)
    split(world, "coordinator", 3)
    before = (AuditEntry.objects.count(), sorted(units(world).values_list("version", flat=True)))
    split(world, "coordinator", 3)
    assert (
        AuditEntry.objects.count(),
        sorted(units(world).values_list("version", flat=True)),
    ) == before


@pytest.mark.parametrize("n", [0, -1, 21])
def test_the_number_must_be_between_one_and_twenty(world, n):
    """Out of range is refused and nothing changes."""
    open_cell(world)
    with pytest.raises(ValidationError):
        split(world, "coordinator", n)
    assert numbers(world) == [] and units(world).count() == 1


def test_a_turma_merged_with_others_for_that_type_cannot_be_split(world):
    """Separate the merge first: the unit has more than one member."""
    open_cell(world)
    other = ClassGroup.objects.create(
        course=world["plan"].course,
        intake_year=world["years"][2026],
        study_plan=world["plan"],
        label="B",
    )
    generate_offerings(world["manager"], [world["semester"]])
    host = units(world).get(members__class_group_link=world["link"])
    other_link = OfferingClassGroup.objects.get(class_group=other)
    TeachingUnit.objects.filter(
        members__class_group_link=other_link, class_type=world["P"]
    ).delete()
    TeachingUnitMember.objects.bulk_create(
        [TeachingUnitMember(unit=host, class_group_link=other_link, class_type=world["P"])]
    )
    with pytest.raises(ValidationError):
        split(world, "coordinator", 2)
    assert numbers(world) == []


def test_a_class_type_the_subject_does_not_have_is_refused(world):
    """Splitting needs a unit of that type to start from."""
    open_cell(world)
    with pytest.raises(ValidationError):
        set_group_count(world["coordinator"], world["link"], ClassType.objects.get(code="L"), 2)


# --- reason, lock, state and permissions -------------------------------------------------------


def test_the_first_split_needs_no_reason_but_changing_it_does(world):
    """D40: the first split is free; changing N or merging back needs a reason."""
    open_cell(world)
    split(world, "coordinator", 2)
    for n in (3, 1):
        with pytest.raises(ValidationError):
            split(world, "coordinator", n, reason="  ")
    assert numbers(world) == [1, 2]


def test_a_stale_view_of_the_units_is_refused(world):
    """The user saw other versions of the units than the stored ones (D54)."""
    open_cell(world)
    seen = {u.pk: u.version for u in units(world)}
    split(world, "coordinator", 2)
    with pytest.raises(ValidationError) as error:
        split(world, "coordinator", 3, reason="x", seen_versions=seen)
    assert "alterado por outra pessoa" in error.value.messages[0]
    assert numbers(world) == [1, 2]


def test_the_manager_splits_before_the_cell_is_opened(world):
    """The manager prepares the offerings before opening the semester (D86)."""
    split(world, "manager", 2)
    assert numbers(world) == [1, 2]


def test_the_coordinator_cannot_split_before_the_cell_is_opened(world):
    """Not opened means the coordinator does not write yet."""
    with pytest.raises(ValidationError):
        split(world, "coordinator", 2)
    assert numbers(world) == []


def test_nobody_splits_in_a_closed_cell(world):
    """Closed is read-only, also for the manager."""
    open_cell(world)
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="done"
    )
    for who in ("coordinator", "manager"):
        with pytest.raises(ValidationError) as error:
            split(world, who, 2, reason="x")
        assert "fechado" in error.value.messages[0]
    assert numbers(world) == []


@pytest.mark.parametrize("who", ["other_coordinator", "teacher"])
def test_only_who_covers_the_coordination_splits(world, who):
    """Another coordination's coordinator, or a teacher, is denied."""
    open_cell(world)
    with pytest.raises(PermissionDenied):
        split(world, who, 2)
    assert numbers(world) == []


def test_every_change_is_audited(world):
    """One entry per row created or deleted, with the actor and the reason."""
    open_cell(world)
    split(world, "coordinator", 2, reason="two labs")
    entries = AuditEntry.objects.filter(actor=world["coordinator"])
    assert entries.filter(entity="dsd.subgroup", action="create").count() == 2
    assert entries.filter(entity="dsd.teachingunit", action="create").count() == 2
    assert entries.filter(entity="dsd.teachingunit", action="delete").count() == 1
    assert {e.reason for e in entries} == {"two labs"}


def test_a_split_without_reason_leaves_a_default_reason_in_the_audit(world):
    """The audit always has a reason, even when the first split gave none."""
    open_cell(world)
    split(world, "coordinator", 2)
    deletion = AuditEntry.objects.filter(entity="dsd.teachingunit", action="delete").get()
    assert deletion.reason.strip()


# --- generation and stale units ----------------------------------------------------------------


def test_generating_again_does_not_bring_back_the_whole_turma_unit(world):
    """The turma has groups for that type: the generator leaves it alone."""
    open_cell(world)
    split(world, "coordinator", 2)
    result = generate_offerings(world["manager"], [world["semester"]])
    assert result.created_units == 0 and units(world).count() == 2
    assert not TeachingUnitMember.objects.filter(
        class_group_link=world["link"], class_type=world["P"]
    ).exists()


def test_group_units_are_not_stale_while_the_plan_calls_for_them(world):
    """Nothing is flagged right after a split."""
    open_cell(world)
    split(world, "coordinator", 2)
    assert generate_offerings(world["manager"], [world["semester"]]).stale_units == 0


def test_group_units_are_stale_when_the_class_type_leaves_the_subject(world):
    """The P load is removed: both group units are flagged, none is deleted."""
    open_cell(world)
    split(world, "coordinator", 2)
    SubjectClassLoad.objects.filter(subject=world["subject"], class_type__code="P").delete()
    result = generate_offerings(world["manager"], [world["semester"]])
    assert result.stale_units == 2 and units(world).count() == 2


def test_group_units_are_stale_when_the_turma_leaves(world):
    """The turma ends: its group units are flagged, none is deleted, the other turma's stay."""
    subject = Subject.objects.create(
        study_plan=world["plan"],
        code="A4",
        name="Disciplina A4",
        ects=Decimal("6"),
        curricular_year=4,
        semester=1,
        coordination=world["coordination"],
        semester_hours=Decimal("75"),
    )
    SubjectClassLoad.objects.create(subject=subject, class_type=world["P"], weekly_hours="3")
    leaving = ClassGroup.objects.create(
        course=world["plan"].course,
        intake_year=world["years"][2023],
        study_plan=world["plan"],
        label="A",
    )
    ClassGroup.objects.create(
        course=world["plan"].course,
        intake_year=world["years"][2023],
        study_plan=world["plan"],
        label="B",
    )
    generate_offerings(world["manager"], [world["semester"]])
    link = OfferingClassGroup.objects.get(class_group=leaving, offering__subject=subject)
    set_group_count(world["manager"], link, world["P"], 2)
    leaving.last_academic_year = world["years"][2025]
    leaving.save()
    result = generate_offerings(world["manager"], [world["semester"]])
    assert result.stale_units == 2
    assert SubGroup.objects.filter(class_group_link=link).count() == 2
