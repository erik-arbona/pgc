"""Tests for the teaching units created with the offerings (T3.1a).

Implements: docs/backlog_fase2.md T3.1; D19 (one teacher per class type of each turma or group),
D70 (hours by class type), D87 (generation), D86 (state of the cell). A teaching unit is an
offering x a class type; its audience is a set of turmas of the offering. By default there is one
unit per turma and class type.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

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
from apps.dsd import services
from apps.dsd.models import Offering, OfferingClassGroup, TeachingUnit, TeachingUnitMember
from apps.dsd.services import change_state, create_dsd, generate_offerings

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    """A manager, a DSD of 2026, one coordination and a plan that starts in 2023."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2025, 2026)}
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="EIC", level="bachelor"),
        academic_year=years[2023],
    )
    manager = django_user_model.objects.create_user(username="m", password="x")
    RoleAssignment.objects.create(
        user=manager, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.FACULTY, scope_id=faculty.pk
    )
    dsd = create_dsd(years[2026], manager)
    return {
        "manager": manager,
        "coordination": coordination,
        "faculty": faculty,
        "years": years,
        "plan": plan,
        "semester": dsd.semesters.get(number=1),
    }


def make_subject(world, code="A1", loads=(("T", "2"), ("TP", "2")), **extra):
    """A first-year, first-semester subject with weekly hours by class type."""
    data = dict(
        study_plan=world["plan"],
        code=code,
        name=f"Disciplina {code}",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=world["coordination"],
        semester_hours=Decimal("60"),
    )
    data.update(extra)
    subject = Subject.objects.create(**data)
    for class_code, hours in loads:
        SubjectClassLoad.objects.create(
            subject=subject, class_type=ClassType.objects.get(code=class_code), weekly_hours=hours
        )
    return subject


def make_turma(world, intake=2026, **extra):
    """A turma of the plan's course."""
    return ClassGroup.objects.create(
        course=world["plan"].course,
        intake_year=world["years"][intake],
        study_plan=world["plan"],
        **extra,
    )


def generate(world, **kwargs):
    """Generate the first semester for the manager."""
    return generate_offerings(world["manager"], [world["semester"]], **kwargs)


def members_of(unit):
    """The turmas that attend a unit."""
    return {m.class_group_link.class_group for m in unit.members.all()}


# --- what is created ---------------------------------------------------------------------------


def test_there_is_one_unit_per_turma_and_class_type(world):
    """A subject with T and TP, taken by one turma, gives two units of one turma each."""
    turma = make_turma(world)
    make_subject(world)
    result = generate(world)
    assert result.created_units == 2
    units = {u.class_type.code: u for u in TeachingUnit.objects.all()}
    assert set(units) == {"T", "TP"}
    assert all(members_of(u) == {turma} for u in units.values())


def test_two_turmas_give_separate_units_by_default(world):
    """A and B are not merged by default: each has its own unit of each type."""
    a = make_turma(world, label="A")
    b = make_turma(world, label="B")
    make_subject(world, loads=(("T", "2"),))
    generate(world)
    units = TeachingUnit.objects.all()
    assert units.count() == 2
    assert sorted(len(members_of(u)) for u in units) == [1, 1]
    assert {next(iter(members_of(u))) for u in units} == {a, b}


def test_a_subject_without_loads_has_no_units(world):
    """No class type, nothing to teach: the offering exists but no unit."""
    make_turma(world)
    make_subject(world, loads=())
    result = generate(world)
    assert result.created_offerings == 1 and result.created_units == 0


def test_the_unit_belongs_to_the_offering_and_its_cell(world):
    """The cell of a unit is the cell of its offering (semester and coordination)."""
    make_turma(world)
    make_subject(world, loads=(("T", "2"),))
    generate(world)
    unit = TeachingUnit.objects.get()
    assert unit.offering == Offering.objects.get()
    assert unit.dsd_cell() == (world["semester"].pk, world["coordination"].pk)


def test_the_other_type_codes_also_get_a_unit(world):
    """Any class type with hours, including 'Outra', is taught and gets a unit (D70)."""
    make_turma(world)
    make_subject(world, loads=(("OUT", "1"),))
    generate(world)
    assert TeachingUnit.objects.get().class_type.code == "OUT"


# --- running it again --------------------------------------------------------------------------


def test_running_it_again_creates_nothing(world):
    """Idempotent: the second run finds every unit in place."""
    make_turma(world)
    make_subject(world)
    generate(world)
    again = generate(world)
    assert again.created_units == 0
    assert TeachingUnit.objects.count() == 2 and TeachingUnitMember.objects.count() == 2


def test_a_class_type_added_later_gets_its_unit(world):
    """The subject gets a lab load after the first run: the next run adds that unit only."""
    make_turma(world)
    subject = make_subject(world, loads=(("T", "2"),))
    generate(world)
    unit = TeachingUnit.objects.get()
    version = unit.version
    SubjectClassLoad.objects.create(
        subject=subject, class_type=ClassType.objects.get(code="P"), weekly_hours="2"
    )
    result = generate(world)
    assert result.created_units == 1 and TeachingUnit.objects.count() == 2
    unit.refresh_from_db()
    assert unit.version == version


def test_a_turma_added_later_gets_its_units(world):
    """Only the new turma's units are created."""
    make_turma(world, label="A")
    make_subject(world, loads=(("T", "2"),))
    generate(world)
    make_turma(world, label="B")
    result = generate(world)
    assert result.created_units == 1 and TeachingUnit.objects.count() == 2


def test_units_of_offerings_generated_before_exist_after_the_next_run(world):
    """Offerings with links but no units (made before T3.1) get their units."""
    turma = make_turma(world)
    subject = make_subject(world, loads=(("T", "2"),))
    generate(world)
    TeachingUnit.objects.all().delete()  # the state of a DSD generated before units existed
    result = generate(world)
    assert result.created_units == 1
    assert members_of(TeachingUnit.objects.get()) == {turma}
    assert Offering.objects.get().subject == subject


# --- what stays when the plan changes ----------------------------------------------------------


def test_a_removed_class_type_leaves_a_stale_unit_that_is_kept(world):
    """The load of TP is removed: its unit is flagged, not deleted."""
    make_turma(world)
    subject = make_subject(world)
    generate(world)
    SubjectClassLoad.objects.filter(subject=subject, class_type__code="TP").delete()
    result = generate(world)
    assert result.stale_units == 1 and TeachingUnit.objects.count() == 2


def test_a_turma_that_ends_leaves_stale_units_that_are_kept(world):
    """The turma no longer takes the subject: its units stay as history, flagged."""
    old = make_turma(world, intake=2023)
    make_subject(world, curricular_year=4, loads=(("T", "2"), ("TP", "2")))
    generate(world)
    old.last_academic_year = world["years"][2025]
    old.save()
    result = generate(world)
    assert result.stale_units == 2 and TeachingUnit.objects.count() == 2


def test_only_the_units_of_the_turma_that_left_are_stale(world):
    """The offering is still wanted (turma B takes it), but turma A's unit is flagged."""
    a = make_turma(world, intake=2023, label="A")
    make_turma(world, intake=2023, label="B")
    make_subject(world, curricular_year=4, loads=(("T", "2"),))
    generate(world)
    a.last_academic_year = world["years"][2025]
    a.save()
    result = generate(world)
    assert result.stale_units == 1 and TeachingUnit.objects.count() == 2


def test_units_that_are_still_wanted_are_not_stale(world):
    """A normal second run flags nothing."""
    make_turma(world)
    make_subject(world)
    generate(world)
    assert generate(world).stale_units == 0


# --- state of the cell, scope and audit --------------------------------------------------------


def test_a_closed_cell_gets_no_units(world):
    """Generation skips the closed cell: nothing is created."""
    make_turma(world)
    make_subject(world)
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="done"
    )
    result = generate(world)
    assert result.created_units == 0 and not TeachingUnit.objects.exists()


def test_every_unit_and_member_is_audited(world):
    """One entry for each unit and each member, with the actor and the reason."""
    make_turma(world)
    make_subject(world, loads=(("T", "2"),))
    generate(world, reason="start of the year")
    entries = AuditEntry.objects.filter(actor=world["manager"])
    assert entries.filter(entity="dsd.teachingunit").count() == 1
    assert entries.filter(entity="dsd.teachingunitmember").count() == 1
    assert {e.reason for e in entries.filter(entity__startswith="dsd.teachingunit")} == {
        "start of the year"
    }


def test_losing_the_race_leaves_no_duplicate_and_no_orphan_unit(world, monkeypatch):
    """A competing request creates the same member first: our unit is rolled back with it."""
    make_turma(world)
    make_subject(world, loads=(("T", "2"),))
    generate(world)
    TeachingUnit.objects.all().delete()  # nothing in place, so our run will try to create
    real = services.audited_save

    def racing(instance, actor, reason=""):
        if isinstance(instance, TeachingUnitMember):
            raise IntegrityError("simulated: another request created the member first")
        return real(instance, actor, reason)

    monkeypatch.setattr(services, "audited_save", racing)
    result = generate(world)
    assert result.created_units == 0 and not TeachingUnit.objects.exists()


# --- the models --------------------------------------------------------------------------------


def make_link(world):
    """A saved offering link, made by the real generation."""
    make_turma(world)
    make_subject(world, loads=(("T", "2"),))
    generate(world)
    TeachingUnit.objects.all().delete()
    return OfferingClassGroup.objects.get()


def test_a_unit_cannot_be_saved_outside_the_guard(world):
    """DSD data is written inside ``dsd_write`` only."""
    link = make_link(world)
    unit = TeachingUnit(offering=link.offering, class_type=ClassType.objects.get(code="T"))
    with pytest.raises(ImproperlyConfigured):
        unit.save()


def test_a_turma_has_one_whole_unit_per_class_type_in_the_database(world):
    """The same turma cannot be a member of two units of the same type."""
    link = make_link(world)
    t = ClassType.objects.get(code="T")
    first, second = TeachingUnit.objects.bulk_create(
        [TeachingUnit(offering=link.offering, class_type=t) for _ in range(2)]
    )
    TeachingUnitMember.objects.bulk_create(
        [TeachingUnitMember(unit=first, class_group_link=link, class_type=t)]
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        TeachingUnitMember.objects.bulk_create(
            [TeachingUnitMember(unit=second, class_group_link=link, class_type=t)]
        )


def test_the_member_class_type_must_match_the_unit(world):
    """The copy of the type on the member cannot disagree with the unit."""
    link = make_link(world)
    t, tp = ClassType.objects.get(code="T"), ClassType.objects.get(code="TP")
    unit = TeachingUnit.objects.bulk_create([TeachingUnit(offering=link.offering, class_type=t)])[0]
    with pytest.raises(ValidationError):
        TeachingUnitMember(unit=unit, class_group_link=link, class_type=tp).clean()


def test_the_things_a_unit_depends_on_cannot_be_deleted(world):
    """The offering, the class type and the turma link are protected by the unit and its members."""
    make_turma(world)
    make_subject(world, loads=(("T", "2"),))
    generate(world)
    unit = TeachingUnit.objects.get()
    # Querysets skip the write guard, which is not what is being tested here.
    with pytest.raises(ProtectedError):
        Offering.objects.filter(pk=unit.offering_id).delete()
    with pytest.raises(ProtectedError):
        unit.class_type.delete()
    with pytest.raises(ProtectedError):
        OfferingClassGroup.objects.filter(unit_memberships__unit=unit).delete()


def test_a_stale_copy_of_a_unit_cannot_be_saved(world):
    """The unit has the optimistic lock (D54): saving an older copy is refused."""
    make_turma(world)
    make_subject(world, loads=(("T", "2"),))
    generate(world)
    first, second = TeachingUnit.objects.get(), TeachingUnit.objects.get()
    from apps.dsd.guard import _ACTIVE

    token = _ACTIVE.set(first.dsd_cell())
    try:
        first.save()
        with pytest.raises(ValidationError):
            second.save()
    finally:
        _ACTIVE.reset(token)
