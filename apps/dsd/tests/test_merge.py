"""Tests for merging turmas and groups of the same course, and separating them (T3.3a).

Implements: docs/backlog_fase2.md T3.3; D23 (merges by class type), D90 (groups, audience of a
unit), D64 (the coordinator sees room quantities by type and capacity, never one room), D86
(state of the cell). A merge is one unit with several members; it is only allowed if some room of
the campus holds the sum of the students, and the coordinator states the capacity (and type) of
room asked, which is saved on the unit as the room request.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Course,
    Enrollment,
    Faculty,
    StudyPlan,
    Subject,
    SubjectClassLoad,
)
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.dsd.models import OfferingClassGroup, SubGroup, TeachingUnit, TeachingUnitMember
from apps.dsd.services import (
    change_state,
    create_dsd,
    generate_offerings,
    merge_units,
    separate_member,
    set_group_count,
    unit_versions,
)
from apps.dsd.sizes import group_students
from apps.rooms.models import Room, RoomType

pytestmark = pytest.mark.django_db


def user_with(django_user_model, profile, kind, scope_id, username):
    """A user with one role."""
    user = django_user_model.objects.create_user(username=username, password="x")
    RoleAssignment.objects.create(user=user, profile=profile, scope_kind=kind, scope_id=scope_id)
    return user


def make_room(number, capacity, type_code=None):
    """A room of the campus; any room type unless one is given."""
    room_type = RoomType.objects.get(code=type_code) if type_code else RoomType.objects.first()
    return Room.objects.create(
        building="Edifício 9", number=number, room_type=room_type, capacity=capacity
    )


@pytest.fixture
def world(django_user_model):
    """A DSD of 2026 with turmas A (30 students) and B (25), subject with T and P, one big room."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    other = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2025, 2026)}
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="EIC", level="bachelor"),
        academic_year=years[2023],
    )
    manager = user_with(django_user_model, Profile.PGC_MANAGER, ScopeKind.FACULTY, faculty.pk, "m")
    turmas = {}
    for label, students in (("A", 30), ("B", 25)):
        turma = ClassGroup.objects.create(
            course=plan.course, intake_year=years[2026], study_plan=plan, label=label
        )
        Enrollment.objects.create(
            class_group=turma, academic_year=years[2026], kind="actual", students=students
        )
        turmas[label] = turma
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
    make_room("101", 60)
    return {
        "manager": manager,
        "coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, coordination.pk, "c"
        ),
        "other_coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, other.pk, "o"
        ),
        "semester": semester,
        "coordination": coordination,
        "turmas": turmas,
        "subject": subject,
        "plan": plan,
        "years": years,
        "links": {
            label: OfferingClassGroup.objects.get(class_group=turma)
            for label, turma in turmas.items()
        },
        "T": ClassType.objects.get(code="T"),
        "P": ClassType.objects.get(code="P"),
    }


def open_cell(world):
    """Open the semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def unit_of(world, label, class_type="T"):
    """The whole-turma unit of a turma for a class type."""
    return TeachingUnit.objects.get(
        members__class_group_link=world["links"][label], class_type=world[class_type]
    )


def group_unit(world, label, number, class_type="P"):
    """The unit of one group of a turma."""
    return TeachingUnit.objects.get(
        members__subgroup__class_group_link=world["links"][label],
        members__subgroup__number=number,
        class_type=world[class_type],
    )


def merge(world, who, units, capacity=55, **kwargs):
    """Merge units asking for a room of ``capacity`` places."""
    return merge_units(world[who], units, capacity, **kwargs)


def members(unit):
    """The turmas and groups of a unit, as short strings such as ``A`` or ``A – P1``."""
    names = []
    for member in unit.members.all():
        if member.subgroup_id:
            group = member.subgroup
            turma = group.class_group_link.class_group.label
            names.append(f"{turma} – {group.class_type.code}{group.number}")
        else:
            names.append(member.class_group_link.class_group.label)
    return sorted(names)


# --- the pure size rule ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("students", "groups", "expected"),
    [(30, 2, 15), (31, 2, 16), (1, 3, 1), (30, 1, 30), (0, 2, 0), (25, 4, 7)],
)
def test_a_group_has_the_turma_size_divided_by_the_groups_rounded_up(students, groups, expected):
    """Size of a group = ceil(turma students / number of groups); one group is the whole turma."""
    assert group_students(students, groups) == expected


def test_a_group_count_below_one_is_an_error():
    """Zero groups makes no sense."""
    with pytest.raises(ValueError):
        group_students(10, 0)


# --- merging -----------------------------------------------------------------------------------


def test_two_whole_turmas_merge_into_one_unit(world):
    """The host keeps both turmas, the other unit is deleted, the room request is saved."""
    open_cell(world)
    a, b = unit_of(world, "A"), unit_of(world, "B")
    version = a.version
    host = merge(world, "coordinator", [a, b], capacity=55)
    assert host.pk == a.pk and members(host) == ["A", "B"]
    assert not TeachingUnit.objects.filter(pk=b.pk).exists()
    host.refresh_from_db()
    assert host.room_capacity == 55 and host.version > version


def test_the_room_request_can_name_a_room_type(world):
    """Type and capacity both asked, as the specification says."""
    open_cell(world)
    room_type = RoomType.objects.get(code=RoomType.objects.first().code)
    host = merge(
        world, "coordinator", [unit_of(world, "A"), unit_of(world, "B")], room_type=room_type
    )
    host.refresh_from_db()
    assert host.room_type == room_type


def test_groups_of_different_turmas_merge(world):
    """Group 1 of A (15) and group 1 of B (13) become one unit of 28."""
    open_cell(world)
    for label in ("A", "B"):
        set_group_count(world["manager"], world["links"][label], world["P"], 2)
    host = merge(
        world, "coordinator", [group_unit(world, "A", 1), group_unit(world, "B", 1)], capacity=28
    )
    assert members(host) == ["A – P1", "B – P1"]
    assert (
        SubGroup.objects.count() == 4
        and TeachingUnit.objects.filter(class_type=world["P"]).count() == 3
    )


def test_a_whole_turma_and_a_group_of_another_turma_merge(world):
    """A small undivided turma can join a group of a divided one."""
    open_cell(world)
    set_group_count(world["manager"], world["links"]["A"], world["P"], 2)
    host = merge(
        world, "coordinator", [group_unit(world, "A", 2), unit_of(world, "B", "P")], capacity=40
    )
    assert members(host) == ["A – P2", "B"]


def test_a_merge_can_take_part_in_another_merge(world):
    """Merging a merged unit with a third brings all its members."""
    open_cell(world)
    extra = ClassGroup.objects.create(
        course=world["plan"].course,
        intake_year=world["years"][2026],
        study_plan=world["plan"],
        label="C",
    )
    Enrollment.objects.create(
        class_group=extra, academic_year=world["years"][2026], kind="actual", students=10
    )
    generate_offerings(world["manager"], [world["semester"]])
    world["links"]["C"] = OfferingClassGroup.objects.get(class_group=extra)
    first = merge(world, "coordinator", [unit_of(world, "A"), unit_of(world, "B")])
    third = unit_of(world, "C")
    make_room("102", 80)  # 30 + 25 + 10 = 65 students
    host = merge(world, "coordinator", [TeachingUnit.objects.get(pk=first.pk), third], capacity=65)
    assert members(host) == ["A", "B", "C"]


def test_the_default_reason_is_recorded_and_every_change_is_audited(world):
    """Each moved member, the host and the deleted unit leave an entry with the actor."""
    open_cell(world)
    a, b = unit_of(world, "A"), unit_of(world, "B")
    merge(world, "coordinator", [a, b])
    entries = AuditEntry.objects.filter(actor=world["coordinator"])
    assert entries.filter(entity="dsd.teachingunitmember", action="update").count() == 1
    assert entries.filter(entity="dsd.teachingunit", action="update").count() == 1
    assert entries.filter(entity="dsd.teachingunit", action="delete").count() == 1
    assert all(e.reason.strip() for e in entries)


# --- merge refusals ----------------------------------------------------------------------------


def test_a_merge_needs_two_distinct_units(world):
    """One unit, or the same unit twice, is not a merge."""
    open_cell(world)
    a = unit_of(world, "A")
    for units in ([a], [a, a]):
        with pytest.raises(ValidationError):
            merge(world, "coordinator", units)


def test_units_of_different_class_types_do_not_merge(world):
    """Theory with practice is not a merge."""
    open_cell(world)
    with pytest.raises(ValidationError):
        merge(world, "coordinator", [unit_of(world, "A", "T"), unit_of(world, "B", "P")])


def test_units_of_different_offerings_do_not_merge(world):
    """Another subject is another offering: that is a merge between subjects, not allowed here."""
    open_cell(world)
    other = Subject.objects.create(
        study_plan=world["plan"],
        code="A2",
        name="Disciplina A2",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=world["coordination"],
        semester_hours=Decimal("75"),
    )
    SubjectClassLoad.objects.create(subject=other, class_type=world["T"], weekly_hours="2")
    generate_offerings(world["manager"], [world["semester"]])
    foreign = TeachingUnit.objects.get(
        offering__subject=other,
        class_type=world["T"],
        members__class_group_link__class_group=world["turmas"]["B"],
    )
    # 30 + 25 = 55 students fit the 60-place room, so only the offering rule can refuse it.
    with pytest.raises(ValidationError) as error:
        merge(world, "coordinator", [unit_of(world, "A"), foreign])
    assert "mesma disciplina" in error.value.messages[0]


def test_two_groups_of_the_same_turma_cannot_be_merged(world):
    """To change how many groups a turma has, change the count instead."""
    open_cell(world)
    set_group_count(world["manager"], world["links"]["A"], world["P"], 3)
    with pytest.raises(ValidationError):
        merge(world, "coordinator", [group_unit(world, "A", 1), group_unit(world, "A", 2)])


def test_an_obsolete_unit_cannot_be_merged(world):
    """The load of T leaves the subject: the T units are obsolete and not mergeable."""
    open_cell(world)
    a, b = unit_of(world, "A"), unit_of(world, "B")
    SubjectClassLoad.objects.filter(subject=world["subject"], class_type=world["T"]).delete()
    with pytest.raises(ValidationError):
        merge(world, "coordinator", [a, b])
    assert members(TeachingUnit.objects.get(pk=a.pk)) == ["A"]


def test_a_merge_with_a_turma_without_enrollment_is_refused(world):
    """Without the number of students the size rule cannot be applied."""
    open_cell(world)
    Enrollment.objects.filter(class_group=world["turmas"]["B"]).delete()
    with pytest.raises(ValidationError) as error:
        merge(world, "coordinator", [unit_of(world, "A"), unit_of(world, "B")])
    assert "matrícula" in error.value.messages[0]


def test_a_merge_no_room_can_hold_is_blocked(world):
    """30 + 25 = 55 students and the biggest room has 60: fine; with 50 places it is blocked."""
    open_cell(world)
    Room.objects.update(capacity=50)
    with pytest.raises(ValidationError) as error:
        merge(world, "coordinator", [unit_of(world, "A"), unit_of(world, "B")], capacity=55)
    assert "sala" in error.value.messages[0].lower()
    assert members(unit_of(world, "A")) == ["A"]


def test_the_room_asked_must_hold_the_students(world):
    """Asking for 40 places for 55 students is refused."""
    open_cell(world)
    with pytest.raises(ValidationError):
        merge(world, "coordinator", [unit_of(world, "A"), unit_of(world, "B")], capacity=40)


def test_a_room_that_does_not_exist_for_the_type_asked_blocks_the_merge(world):
    """Rooms of the asked type must exist with enough places."""
    open_cell(world)
    other_type = RoomType.objects.exclude(pk=Room.objects.first().room_type_id).first()
    with pytest.raises(ValidationError):
        merge(
            world,
            "coordinator",
            [unit_of(world, "A"), unit_of(world, "B")],
            room_type=other_type,
        )


def test_a_stale_view_of_the_units_is_refused(world):
    """The user saw other versions than the stored ones (D54)."""
    open_cell(world)
    a, b = unit_of(world, "A"), unit_of(world, "B")
    seen = {a.pk: a.version, b.pk: b.version}
    set_group_count(world["manager"], world["links"]["A"], world["P"], 2)  # other unit; no effect
    TeachingUnit.objects.filter(pk=a.pk).update(version=a.version + 1)
    with pytest.raises(ValidationError) as error:
        merge(world, "coordinator", [a, b], seen_versions=seen)
    assert "alterado por outra pessoa" in error.value.messages[0]


def test_nobody_merges_in_a_closed_cell(world):
    """Closed is read-only, also for the manager."""
    open_cell(world)
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="done"
    )
    for who in ("coordinator", "manager"):
        with pytest.raises(ValidationError):
            merge(world, who, [unit_of(world, "A"), unit_of(world, "B")])


def test_the_coordinator_cannot_merge_before_the_cell_is_opened_but_the_manager_can(world):
    """Not opened: only the manager prepares."""
    with pytest.raises(ValidationError):
        merge(world, "coordinator", [unit_of(world, "A"), unit_of(world, "B")])
    host = merge(world, "manager", [unit_of(world, "A"), unit_of(world, "B")])
    assert members(host) == ["A", "B"]


def test_a_coordinator_of_another_coordination_is_denied(world):
    """The scope is checked whatever the state."""
    open_cell(world)
    with pytest.raises(PermissionDenied):
        merge(world, "other_coordinator", [unit_of(world, "A"), unit_of(world, "B")])


# --- separating --------------------------------------------------------------------------------


def merged(world):
    """A and B merged for T; returns the host."""
    open_cell(world)
    return merge(world, "coordinator", [unit_of(world, "A"), unit_of(world, "B")])


def test_separating_gives_the_member_a_unit_of_its_own_without_a_room_request(world):
    """The separated turma starts alone and without room request; the host keeps its own."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["B"])
    new = separate_member(world["coordinator"], host, member, reason="rooms changed")
    assert members(new) == ["B"] and new.room_capacity is None and new.room_type is None
    host.refresh_from_db()
    assert members(host) == ["A"] and host.room_capacity == 55


def test_separating_needs_a_reason(world):
    """D40: undoing a merge needs one."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["B"])
    with pytest.raises(ValidationError):
        separate_member(world["coordinator"], host, member, reason=" ")
    assert members(TeachingUnit.objects.get(pk=host.pk)) == ["A", "B"]


def test_the_last_member_cannot_be_separated(world):
    """A unit with one member has nothing to separate."""
    open_cell(world)
    a = unit_of(world, "A")
    with pytest.raises(ValidationError):
        separate_member(world["coordinator"], a, a.members.get(), reason="x")


def test_a_member_of_another_unit_cannot_be_separated(world):
    """The member must belong to the unit given."""
    host = merged(world)
    other_member = TeachingUnit.objects.get(
        class_type=world["P"], members__class_group_link=world["links"]["A"]
    ).members.get()
    with pytest.raises(ValidationError):
        separate_member(world["coordinator"], host, other_member, reason="x")


def test_separating_with_a_stale_version_is_refused(world):
    """Someone else changed the unit after it was loaded (D54)."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["B"])
    with pytest.raises(ValidationError):
        separate_member(
            world["coordinator"], host, member, reason="x", seen_version=host.version - 1
        )


def test_separating_after_a_closing_is_refused(world):
    """Closed cells do not change, not even to undo a merge."""
    host = merged(world)
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="done"
    )
    member = host.members.get(class_group_link=world["links"]["B"])
    with pytest.raises(ValidationError):
        separate_member(world["manager"], host, member, reason="x")


# --- interplay ---------------------------------------------------------------------------------


def test_the_generator_does_not_recreate_merged_units(world):
    """After a merge, generating again creates nothing and flags nothing."""
    merged(world)
    result = generate_offerings(world["manager"], [world["semester"]])
    assert result.created_units == 0 and result.stale_units == 0
    assert TeachingUnit.objects.filter(class_type=world["T"]).count() == 1


def test_the_generator_stays_idempotent_after_a_separation(world):
    """The separated turma has its unit; generating again adds nothing."""
    host = merged(world)
    separate_member(
        world["coordinator"], host, host.members.get(class_group_link=world["links"]["B"]), "x"
    )
    assert generate_offerings(world["manager"], [world["semester"]]).created_units == 0
    assert TeachingUnit.objects.filter(class_type=world["T"]).count() == 2


def test_a_merged_turma_cannot_be_divided_until_it_is_separated(world):
    """set_group_count refuses on the merged unit and works after separating."""
    host = merged(world)
    with pytest.raises(ValidationError) as error:
        set_group_count(world["coordinator"], world["links"]["A"], world["T"], 2, "x")
    assert "separ" in error.value.messages[0].lower()
    separate_member(
        world["coordinator"], host, host.members.get(class_group_link=world["links"]["A"]), "x"
    )
    set_group_count(world["coordinator"], world["links"]["A"], world["T"], 2, "x")
    assert (
        SubGroup.objects.filter(class_group_link=world["links"]["A"], class_type=world["T"]).count()
        == 2
    )


def test_unit_versions_include_a_merged_unit_for_each_of_its_turmas(world):
    """The versions the group form carries see the merged unit through any member."""
    host = merged(world)
    assert set(unit_versions(world["links"]["A"], world["T"])) == {host.pk}
    assert set(unit_versions(world["links"]["B"], world["T"])) == {host.pk}
    assert TeachingUnitMember.objects.filter(unit=host).count() == 2
