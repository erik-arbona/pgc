"""Tests for the adapter from the DSD models to the pure load rules (T5.1b).

Implements: docs/backlog_fase2.md T5.1; D70 (a merge counts once, N groups count N times), D71
(preparation), D72-D74 (annual load and state), D92 (a cross-course merge counts the hours of the
host's subject), D94 (one teacher per unit, always 100%). Nothing is stored: it is computed when
asked, with a fixed number of queries.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Course,
    CrossCourseSubject,
    CrossCourseSubjectCourse,
    CrossCourseSubjectMember,
    Enrollment,
    Faculty,
    StudyPlan,
    Subject,
    SubjectClassLoad,
)
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.dsd.load_facts import teacher_loads, unit_facts
from apps.dsd.load_status import LoadStatus
from apps.dsd.models import OfferingClassGroup, TeachingUnit
from apps.dsd.services import (
    assign_teacher,
    create_dsd,
    generate_offerings,
    merge_units,
    set_group_count,
)
from apps.rooms.models import Room, RoomType
from apps.staff.models import Category, LoadRange, Teacher

pytestmark = pytest.mark.django_db

AS_OF = date(2026, 11, 1)


def make_teacher(coordination, identifier):
    """A full-time teacher of a coordination."""
    return Teacher.objects.create(
        identifier=identifier,
        name=f"Docente {identifier}",
        coordination=coordination,
        category=Category.objects.get(name="Doutor"),
        teacher_type=Teacher.Type.FULL_TIME,
    )


def make_subject(plan, coordination, code, semester=1, hours=(("T", "2"), ("P", "3"))):
    """A first-year subject with weekly hours by class type."""
    subject = Subject.objects.create(
        study_plan=plan,
        code=code,
        name=f"Disciplina {code}",
        ects=Decimal("6"),
        curricular_year=1,
        semester=semester,
        coordination=coordination,
        semester_hours=Decimal("75"),
    )
    for class_code, weekly in hours:
        SubjectClassLoad.objects.create(
            subject=subject,
            class_type=ClassType.objects.get(code=class_code),
            weekly_hours=weekly,
        )
    return subject


@pytest.fixture
def world(django_user_model):
    """EIC (turmas A, B) and EEC (turma E) in one coordination, a DSD, a full-time range."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2026)}
    courses = {
        name: Course.objects.create(faculty=faculty, name=name, level="bachelor")
        for name in ("EIC", "EEC")
    }
    plans = {
        name: StudyPlan.objects.create(course=course, academic_year=years[2023])
        for name, course in courses.items()
    }
    turmas = {}
    for key, course, label, students in (
        ("A", "EIC", "A", 30),
        ("B", "EIC", "B", 25),
        ("E", "EEC", "E", 20),
    ):
        turmas[key] = ClassGroup.objects.create(
            course=courses[course], intake_year=years[2026], study_plan=plans[course], label=label
        )
        Enrollment.objects.create(
            class_group=turmas[key], academic_year=years[2026], kind="actual", students=students
        )
    manager = django_user_model.objects.create_user(username="m", password="x")
    RoleAssignment.objects.create(
        user=manager, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.FACULTY, scope_id=faculty.pk
    )
    subjects = {
        "EIC": make_subject(plans["EIC"], coordination, "A1"),
        "EEC": make_subject(plans["EEC"], coordination, "B1", hours=(("T", "2"), ("P", "2"))),
    }
    group = CrossCourseSubject.objects.create(name="Matemática")
    for subject in subjects.values():
        CrossCourseSubjectMember.objects.create(cross_course_subject=group, subject=subject)
    for course in courses.values():
        CrossCourseSubjectCourse.objects.create(cross_course_subject=group, course=course)
    LoadRange.objects.create(
        kind=LoadRange.Kind.CATEGORY,
        category=Category.objects.get(name="Doutor"),
        minimum_hours=Decimal("6"),
        maximum_hours=Decimal("12"),
        valid_from=date(2020, 1, 1),
    )
    dsd = create_dsd(years[2026], manager)
    sem1 = dsd.semesters.get(number=1)
    generate_offerings(manager, [sem1])
    Room.objects.create(
        building="Edifício 9", number="101", room_type=RoomType.objects.first(), capacity=100
    )
    return {
        "manager": manager,
        "coordination": coordination,
        "faculty": faculty,
        "dsd": dsd,
        "sem1": sem1,
        "sem2": dsd.semesters.get(number=2),
        "subjects": subjects,
        "plans": plans,
        "years": years,
        "turmas": turmas,
        "links": {k: OfferingClassGroup.objects.get(class_group=t) for k, t in turmas.items()},
        "ana": make_teacher(coordination, "ANA"),
        "rui": make_teacher(coordination, "RUI"),
        "T": ClassType.objects.get(code="T"),
        "P": ClassType.objects.get(code="P"),
    }


def unit_of(world, key, class_type="T"):
    """The whole-turma unit of a turma for a class type."""
    return TeachingUnit.objects.get(
        members__class_group_link=world["links"][key], class_type=world[class_type]
    )


def give(world, unit, teacher):
    """Give a teacher to a unit, as the manager."""
    assign_teacher(world["manager"], unit, teacher)


# --- the facts ---------------------------------------------------------------------------------


def test_a_unit_with_a_teacher_becomes_a_fact_with_the_hours_of_its_subject(world):
    """T of turma A, 2 weekly hours, taught by Ana at 100%."""
    give(world, unit_of(world, "A"), world["ana"])
    facts, without_hours = unit_facts(world["sem1"])
    (fact,) = [
        f for f in facts if f.class_type == "T" and world["turmas"]["A"].pk in f.class_group_ids
    ]
    assert fact.weekly_hours == Decimal("2.00")
    assert [(a.teacher_id, a.share) for a in fact.assignments] == [
        (world["ana"].pk, Decimal("100"))
    ]
    assert without_hours == []


def test_units_without_a_teacher_are_not_facts(world):
    """Only taught units count for a teacher's load."""
    facts, _ = unit_facts(world["sem1"])
    assert facts == []


def test_a_merged_unit_is_one_fact_with_all_its_turmas(world):
    """A and B merged for T: one unit, counted once (D70)."""
    host = merge_units(world["manager"], [unit_of(world, "A"), unit_of(world, "B")], 60)
    give(world, host, world["ana"])
    facts, _ = unit_facts(world["sem1"])
    (fact,) = facts
    assert fact.class_group_ids == frozenset({world["turmas"]["A"].pk, world["turmas"]["B"].pk})


def test_the_groups_of_a_turma_are_facts_of_their_own(world):
    """A turma divided in 2 for P: two units, each a fact with its group."""
    set_group_count(world["manager"], world["links"]["A"], world["P"], 2)
    for unit in TeachingUnit.objects.filter(class_type=world["P"], members__subgroup__isnull=False):
        give(world, unit, world["ana"])
    facts, _ = unit_facts(world["sem1"])
    assert len(facts) == 2 and all(f.subgroup_id is not None for f in facts)


def test_a_cross_course_merge_counts_the_hours_of_the_host_subject(world):
    """EIC P has 3 h, EEC P has 2 h: the host's subject decides (D92)."""
    eic, eec = unit_of(world, "A", "P"), unit_of(world, "E", "P")
    host = merge_units(world["manager"], [eic, eec], 60, host=eec, accept_load_difference=True)
    give(world, host, world["ana"])
    (fact,) = unit_facts(world["sem1"])[0]
    assert fact.weekly_hours == Decimal("2.00")


def test_a_unit_whose_class_type_left_the_subject_is_reported_not_dropped(world):
    """It cannot be a fact (no hours) but it is named, never silently lost."""
    unit = unit_of(world, "A", "P")
    give(world, unit, world["ana"])
    SubjectClassLoad.objects.filter(
        subject=world["subjects"]["EIC"], class_type=world["P"]
    ).delete()
    facts, without_hours = unit_facts(world["sem1"])
    assert facts == [] and without_hours == [unit.pk]


def test_the_facts_can_be_limited_to_some_teachers(world):
    """Only the units taught by the teachers asked for."""
    give(world, unit_of(world, "A"), world["ana"])
    give(world, unit_of(world, "B"), world["rui"])
    facts, _ = unit_facts(world["sem1"], teacher_ids={world["rui"].pk})
    assert [a.teacher_id for f in facts for a in f.assignments] == [world["rui"].pk]


# --- the loads ---------------------------------------------------------------------------------


def test_the_semester_hours_use_the_weeks_of_the_semester(world):
    """Ana teaches T (2 h/week): 2.00 weekly in the semester."""
    give(world, unit_of(world, "A"), world["ana"])
    loads = teacher_loads(world["dsd"], [world["ana"]], AS_OF)
    assert loads[world["ana"].pk].assessment.semester_weekly_hours == (
        Decimal("2.00"),
        Decimal("0.00"),
    )


def test_a_teacher_without_units_still_has_a_load_and_a_state(world):
    """Zero hours, compared with the minimum of the range."""
    load = teacher_loads(world["dsd"], [world["ana"]], AS_OF)[world["ana"].pk]
    assert (
        load.assessment.weekly_hours == Decimal("0")
        and load.assessment.status == LoadStatus.BELOW_MINIMUM
    )


def test_the_state_follows_the_range(world):
    """5 h < 6 min: below; 12 h: at the maximum; 13 h: above, with 1 extra hour."""
    give(world, unit_of(world, "A", "T"), world["ana"])  # 2 h
    give(world, unit_of(world, "A", "P"), world["ana"])  # 3 h
    assert (
        teacher_loads(world["dsd"], [world["ana"]], AS_OF)[world["ana"].pk].assessment.status
        == LoadStatus.BELOW_MINIMUM
    )
    give(world, unit_of(world, "B", "T"), world["ana"])  # 7 h
    give(world, unit_of(world, "B", "P"), world["ana"])  # 10 h
    assert (
        teacher_loads(world["dsd"], [world["ana"]], AS_OF)[world["ana"].pk].assessment.status
        == LoadStatus.IN_RANGE
    )
    give(world, unit_of(world, "E", "T"), world["ana"])  # 12 h
    assessment = teacher_loads(world["dsd"], [world["ana"]], AS_OF)[world["ana"].pk].assessment
    assert (assessment.weekly_hours, assessment.status) == (Decimal("12.00"), LoadStatus.AT_MAXIMUM)
    give(world, unit_of(world, "E", "P"), world["ana"])  # 14 h (EEC P is 2 h)
    assessment = teacher_loads(world["dsd"], [world["ana"]], AS_OF)[world["ana"].pk].assessment
    assert (assessment.weekly_hours, assessment.status, assessment.extra_hours) == (
        Decimal("14.00"),
        LoadStatus.ABOVE_MAXIMUM,
        Decimal("2.00"),
    )


def test_a_teacher_without_a_range_has_no_range(world):
    """No rule in force on the date: a gap in the data, not an error."""
    LoadRange.objects.all().delete()
    load = teacher_loads(world["dsd"], [world["ana"]], AS_OF)[world["ana"].pk]
    assert load.assessment.status == LoadStatus.NO_RANGE


def test_the_two_semesters_add_up_in_the_annual_load(world):
    """T in the 1st semester (2 h) and a 2nd-semester subject (3 h) make 5 h."""
    second_subject = make_subject(
        world["plans"]["EIC"], world["coordination"], "A2", semester=2, hours=(("T", "3"),)
    )
    generate_offerings(world["manager"], [world["sem2"]])
    give(world, unit_of(world, "A", "T"), world["ana"])
    unit2 = TeachingUnit.objects.filter(offering__subject=second_subject).first()
    give(world, unit2, world["ana"])
    load = teacher_loads(world["dsd"], [world["ana"]], AS_OF)[world["ana"].pk]
    assert load.assessment.semester_weekly_hours == (Decimal("2.00"), Decimal("3.00"))
    assert load.assessment.weekly_hours == Decimal("5.00")


def test_the_preparation_uses_the_weights_of_the_class_types(world):
    """Weekly preparation = hours by class type x its weight, per semester."""
    give(world, unit_of(world, "A", "T"), world["ana"])
    give(world, unit_of(world, "A", "P"), world["ana"])
    load = teacher_loads(world["dsd"], [world["ana"]], AS_OF)[world["ana"].pk]
    expected = (
        Decimal("2") * world["T"].preparation_weight + Decimal("3") * world["P"].preparation_weight
    )
    assert load.preparation == (expected.quantize(Decimal("0.01")), Decimal("0.00"))


def test_the_teacher_filter_includes_units_of_every_coordination(world):
    """A teacher who moved to another coordination still counts all their units."""
    give(world, unit_of(world, "A"), world["ana"])
    other = Coordination.objects.create(faculty=world["faculty"], name="Coordenação B")
    Teacher.objects.filter(pk=world["ana"].pk).update(coordination=other)
    ana = Teacher.objects.get(pk=world["ana"].pk)
    load = teacher_loads(world["dsd"], [ana], AS_OF)[ana.pk]
    assert load.assessment.weekly_hours == Decimal("2.00")


def test_the_number_of_queries_does_not_grow_with_the_units(world):
    """A fixed number of queries, whatever the number of taught units."""
    give(world, unit_of(world, "A", "T"), world["ana"])
    with CaptureQueriesContext(connection) as few:
        teacher_loads(world["dsd"], [world["ana"], world["rui"]], AS_OF)
    for key in ("B", "E"):
        give(world, unit_of(world, key, "T"), world["ana"])
        give(world, unit_of(world, key, "P"), world["rui"])
    with CaptureQueriesContext(connection) as many:
        teacher_loads(world["dsd"], [world["ana"], world["rui"]], AS_OF)
    assert len(many) == len(few)


def test_the_text_of_a_state_names_the_extra_hours_above_the_maximum(world):
    """Above the maximum the text says how many hours are extra; the other states do not."""
    from apps.dsd.load_facts import status_text

    for key, class_type in (("A", "T"), ("A", "P"), ("B", "T"), ("B", "P"), ("E", "T"), ("E", "P")):
        give(world, unit_of(world, key, class_type), world["ana"])
    assessment = teacher_loads(world["dsd"], [world["ana"]], AS_OF)[world["ana"].pk].assessment
    assert status_text(assessment) == "acima do máximo (+2.00 h)"
    free = teacher_loads(world["dsd"], [world["rui"]], AS_OF)[world["rui"].pk].assessment
    assert status_text(free) == "abaixo do mínimo"
