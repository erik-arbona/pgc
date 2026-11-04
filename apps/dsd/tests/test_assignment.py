"""Tests for the teacher of a teaching unit (T5.1a).

Implements: docs/backlog_fase2.md T5.1; D19 (one teacher per teaching unit; the sharing with
percentages was dropped, D94), D69 (only teachers of the coordination of the subject), D40
(reason), D54 (versions), D86 (state of the cell), D90/D91 (groups and merges with teachers).
"""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError

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
from apps.dsd.models import Offering, OfferingClassGroup, TeachingUnit
from apps.dsd.services import (
    assign_teacher,
    change_state,
    create_dsd,
    generate_offerings,
    merge_units,
    separate_member,
    set_group_count,
    unassign_teacher,
)
from apps.rooms.models import Room, RoomType
from apps.staff.models import Category, Teacher

pytestmark = pytest.mark.django_db


def make_teacher(coordination, identifier, active=True):
    """A teacher of a coordination."""
    return Teacher.objects.create(
        identifier=identifier,
        name=f"Docente {identifier}",
        coordination=coordination,
        category=Category.objects.get(name="Doutor"),
        teacher_type=Teacher.Type.FULL_TIME,
        is_active=active,
    )


def user_with(django_user_model, profile, kind, scope_id, username):
    """A user with one role."""
    user = django_user_model.objects.create_user(username=username, password="x")
    RoleAssignment.objects.create(user=user, profile=profile, scope_kind=kind, scope_id=scope_id)
    return user


@pytest.fixture
def world(django_user_model):
    """Turmas A (30) and B (25), a subject with T and P, teachers of two coordinations, a room."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    other = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2026)}
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="EIC", level="bachelor"),
        academic_year=years[2023],
    )
    manager = user_with(django_user_model, Profile.PGC_MANAGER, ScopeKind.FACULTY, faculty.pk, "m")
    turmas = {}
    for label, students in (("A", 30), ("B", 25)):
        turmas[label] = ClassGroup.objects.create(
            course=plan.course, intake_year=years[2026], study_plan=plan, label=label
        )
        Enrollment.objects.create(
            class_group=turmas[label], academic_year=years[2026], kind="actual", students=students
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
    Room.objects.create(
        building="Edifício 9", number="101", room_type=RoomType.objects.first(), capacity=80
    )
    return {
        "manager": manager,
        "coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, coordination.pk, "c"
        ),
        "other_coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, other.pk, "o"
        ),
        "teacher_user": user_with(django_user_model, Profile.TEACHER, ScopeKind.NONE, None, "tu"),
        "semester": semester,
        "coordination": coordination,
        "offering": Offering.objects.get(),
        "links": {
            label: OfferingClassGroup.objects.get(class_group=turma)
            for label, turma in turmas.items()
        },
        "mine": make_teacher(coordination, "T1"),
        "mine2": make_teacher(coordination, "T2"),
        "foreign": make_teacher(other, "T3"),
        "inactive": make_teacher(coordination, "T4", active=False),
        "T": ClassType.objects.get(code="T"),
        "P": ClassType.objects.get(code="P"),
    }


def open_cell(world):
    """Open the semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def unit_of(world, label, class_type="T"):
    """The whole-turma unit of a turma for a class type, as stored."""
    return TeachingUnit.objects.get(
        members__class_group_link=world["links"][label], class_type=world[class_type]
    )


# --- assigning ---------------------------------------------------------------------------------


def test_the_coordinator_assigns_a_teacher_of_the_coordination(world):
    """One teacher on the unit."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    assert unit_of(world, "A").teacher == world["mine"]


def test_the_teachers_of_a_unit_are_independent_of_the_other_units(world):
    """Theory and practice of the same turma can have different teachers (D19)."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A", "T"), world["mine"])
    assign_teacher(world["coordinator"], unit_of(world, "A", "P"), world["mine2"])
    assert unit_of(world, "A", "T").teacher != unit_of(world, "A", "P").teacher
    assert unit_of(world, "B", "T").teacher is None


def test_the_same_teacher_can_teach_several_units(world):
    """A teacher is not limited to one unit."""
    open_cell(world)
    for label in ("A", "B"):
        assign_teacher(world["coordinator"], unit_of(world, label), world["mine"])
    assert world["mine"].teaching_units.count() == 2


def test_the_manager_assigns_before_the_cell_is_opened_and_the_coordinator_cannot(world):
    """Not opened: only the manager prepares (D86)."""
    with pytest.raises(ValidationError):
        assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    assign_teacher(world["manager"], unit_of(world, "A"), world["mine"])
    assert unit_of(world, "A").teacher == world["mine"]


def test_nobody_assigns_in_a_closed_cell(world):
    """Closed is read-only, also for the manager."""
    open_cell(world)
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="done"
    )
    for who in ("coordinator", "manager"):
        with pytest.raises(ValidationError):
            assign_teacher(world[who], unit_of(world, "A"), world["mine"])


@pytest.mark.parametrize("who", ["other_coordinator", "teacher_user"])
def test_only_who_covers_the_coordination_assigns(world, who):
    """Another coordination's coordinator, or a teacher, is denied."""
    open_cell(world)
    with pytest.raises(PermissionDenied):
        assign_teacher(world[who], unit_of(world, "A"), world["mine"])
    assert unit_of(world, "A").teacher is None


def test_a_teacher_of_another_coordination_is_refused(world):
    """Only teachers of the coordination of the subject (D69)."""
    open_cell(world)
    with pytest.raises(ValidationError):
        assign_teacher(world["coordinator"], unit_of(world, "A"), world["foreign"])
    assert unit_of(world, "A").teacher is None


def test_an_inactive_teacher_is_refused(world):
    """An inactive teacher cannot be given a new unit."""
    open_cell(world)
    with pytest.raises(ValidationError):
        assign_teacher(world["coordinator"], unit_of(world, "A"), world["inactive"])


def test_a_teacher_deactivated_later_keeps_the_assignment(world):
    """Existing assignments are not touched when a teacher is deactivated."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    Teacher.objects.filter(pk=world["mine"].pk).update(is_active=False)
    assert unit_of(world, "A").teacher == world["mine"]


def test_an_obsolete_unit_cannot_be_given_a_teacher(world):
    """The load of T leaves the subject: its units are obsolete."""
    open_cell(world)
    unit = unit_of(world, "A", "T")
    SubjectClassLoad.objects.filter(
        subject=world["offering"].subject, class_type=world["T"]
    ).delete()
    with pytest.raises(ValidationError):
        assign_teacher(world["coordinator"], unit, world["mine"])


# --- changing and removing ---------------------------------------------------------------------


def test_the_first_teacher_needs_no_reason_but_leaves_one_in_the_audit(world):
    """D40: a default reason is recorded."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    entry = AuditEntry.objects.filter(entity="dsd.teachingunit", action="update").latest("pk")
    assert entry.actor == world["coordinator"] and entry.reason.strip()
    assert entry.old_value["teacher"] is None and entry.new_value["teacher"] == world["mine"].pk


def test_replacing_the_teacher_needs_a_reason(world):
    """Another teacher on a unit that has one."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    with pytest.raises(ValidationError):
        assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine2"], reason=" ")
    assert unit_of(world, "A").teacher == world["mine"]
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine2"], reason="swap")
    assert unit_of(world, "A").teacher == world["mine2"]


def test_removing_the_teacher_needs_a_reason(world):
    """Taking the teacher off is a change as well."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    with pytest.raises(ValidationError):
        unassign_teacher(world["coordinator"], unit_of(world, "A"), reason=" ")
    unassign_teacher(world["coordinator"], unit_of(world, "A"), reason="leaves the course")
    assert unit_of(world, "A").teacher is None


def test_the_same_teacher_writes_nothing(world):
    """No change, no version bump and no audit entry."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    before = (unit_of(world, "A").version, AuditEntry.objects.count())
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    assert (unit_of(world, "A").version, AuditEntry.objects.count()) == before


def test_removing_from_a_unit_without_teacher_writes_nothing(world):
    """Nothing to remove."""
    open_cell(world)
    before = AuditEntry.objects.count()
    unassign_teacher(world["coordinator"], unit_of(world, "A"), reason="x")
    assert AuditEntry.objects.count() == before


def test_a_stale_version_is_refused(world):
    """Someone else changed the unit after it was loaded (D54)."""
    open_cell(world)
    seen = unit_of(world, "A").version
    assign_teacher(world["manager"], unit_of(world, "A"), world["mine"])
    with pytest.raises(ValidationError) as error:
        assign_teacher(
            world["coordinator"],
            unit_of(world, "A"),
            world["mine2"],
            reason="x",
            seen_version=seen,
        )
    assert "alterado por outra pessoa" in error.value.messages[0]
    assert unit_of(world, "A").teacher == world["mine"]


# --- merges, separations and groups ------------------------------------------------------------


def test_merging_two_units_with_teachers_is_refused(world):
    """Which teacher would stay? The coordinator removes one first."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    assign_teacher(world["coordinator"], unit_of(world, "B"), world["mine2"])
    with pytest.raises(ValidationError) as error:
        merge_units(world["coordinator"], [unit_of(world, "A"), unit_of(world, "B")], 60)
    assert "docente" in error.value.messages[0]


def test_merging_keeps_the_only_teacher_when_the_unit_that_has_it_stays(world):
    """One unit with teacher as host: the merge keeps that teacher."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    host = merge_units(
        world["coordinator"],
        [unit_of(world, "B"), unit_of(world, "A")],
        60,
        host=unit_of(world, "A"),
    )
    assert host.teacher == world["mine"] and host.members.count() == 2


def test_merging_picks_the_unit_with_the_teacher_as_host_by_default(world):
    """Without a chosen host the unit that has the teacher stays."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "B"), world["mine"])
    host = merge_units(world["coordinator"], [unit_of(world, "A"), unit_of(world, "B")], 60)
    assert host.teacher == world["mine"]


def test_merging_with_the_teacher_in_a_unit_that_would_go_is_refused(world):
    """Choosing as host the unit without teacher would lose the teacher of the other."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    with pytest.raises(ValidationError):
        merge_units(
            world["coordinator"],
            [unit_of(world, "A"), unit_of(world, "B")],
            60,
            host=unit_of(world, "B"),
        )
    assert unit_of(world, "A").teacher == world["mine"]


def test_a_separated_member_starts_without_teacher(world):
    """The unit it leaves keeps its own."""
    open_cell(world)
    host = merge_units(world["coordinator"], [unit_of(world, "A"), unit_of(world, "B")], 60)
    assign_teacher(world["coordinator"], host, world["mine"])
    member = host.members.get(class_group_link=world["links"]["B"])
    new = separate_member(world["coordinator"], host, member, reason="rooms changed")
    assert new.teacher is None
    assert TeachingUnit.objects.get(pk=host.pk).teacher == world["mine"]


def test_dividing_a_turma_that_has_a_teacher_is_refused(world):
    """The teacher would be lost: remove it first."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A", "P"), world["mine"])
    with pytest.raises(ValidationError) as error:
        set_group_count(world["coordinator"], world["links"]["A"], world["P"], 2)
    assert "docente" in error.value.messages[0]
    assert unit_of(world, "A", "P").teacher == world["mine"]


def test_dividing_works_after_removing_the_teacher(world):
    """Unassign first and then divide."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A", "P"), world["mine"])
    unassign_teacher(world["coordinator"], unit_of(world, "A", "P"), reason="to divide")
    set_group_count(world["coordinator"], world["links"]["A"], world["P"], 2)
    assert TeachingUnit.objects.filter(class_type=world["P"]).count() == 3


def test_going_down_in_groups_refuses_to_drop_a_group_with_a_teacher(world):
    """Dropping group 3 with a teacher is refused; the teacher is removed first."""
    open_cell(world)
    set_group_count(world["coordinator"], world["links"]["A"], world["P"], 3)
    third = TeachingUnit.objects.get(
        members__subgroup__class_group_link=world["links"]["A"], members__subgroup__number=3
    )
    assign_teacher(world["coordinator"], third, world["mine"])
    with pytest.raises(ValidationError):
        set_group_count(world["coordinator"], world["links"]["A"], world["P"], 2, "fewer")
    assert (
        TeachingUnit.objects.filter(class_type=world["P"], members__subgroup__isnull=False).count()
        == 3
    )


def test_the_generator_does_not_touch_the_teachers(world):
    """Generating again leaves the assignments as they are."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    result = generate_offerings(world["manager"], [world["semester"]])
    assert result.created_units == 0 and unit_of(world, "A").teacher == world["mine"]


# --- deleting a teacher ------------------------------------------------------------------------


def test_a_teacher_with_assignments_cannot_be_deleted(world):
    """T0.5: the unit protects its teacher."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A"), world["mine"])
    with pytest.raises(ProtectedError):
        world["mine"].delete()


def test_a_teacher_without_assignments_can_still_be_deleted(world):
    """Nothing uses the teacher."""
    world["mine2"].delete()
    assert not Teacher.objects.filter(identifier="T2").exists()
