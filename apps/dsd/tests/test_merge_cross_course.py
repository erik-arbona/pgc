"""Tests for merging units of different courses in transversal subjects (T3.4a).

Implements: docs/backlog_fase2.md T3.4; D22, D47 (cross-course subjects, indicated courses), D48
(a member counts only while its plan is in force), D91 (merges), Q8 resolved by default (D92):
same coordination only, warning and confirmation when the weekly load differs, and the hours
count under the unit that stays.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

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
from apps.dsd.models import OfferingClassGroup, TeachingUnit
from apps.dsd.services import (
    change_state,
    create_dsd,
    generate_offerings,
    merge_load_differences,
    merge_units,
    separate_member,
    set_group_count,
    stale_unit_ids,
)
from apps.rooms.models import Room, RoomType

pytestmark = pytest.mark.django_db


def make_subject(plan, coordination, code, semester=1, p_hours="3"):
    """A first-year subject of a plan with T (2 h) and P loads."""
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
    for code_, hours in (("T", "2"), ("P", p_hours)):
        SubjectClassLoad.objects.create(
            subject=subject, class_type=ClassType.objects.get(code=code_), weekly_hours=hours
        )
    return subject


@pytest.fixture
def world(django_user_model):
    """EIC (turma A, 30 students) and EEC (turma E, 24), one transversal subject, a big room."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    other_coordination = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2025, 2026)}
    courses, plans, turmas = {}, {}, {}
    for name, students in (("EIC", 30), ("EEC", 24)):
        courses[name] = Course.objects.create(faculty=faculty, name=name, level="bachelor")
        plans[name] = StudyPlan.objects.create(course=courses[name], academic_year=years[2023])
        turmas[name] = ClassGroup.objects.create(
            course=courses[name],
            intake_year=years[2026],
            study_plan=plans[name],
            label=name[-1],
        )
        Enrollment.objects.create(
            class_group=turmas[name], academic_year=years[2026], kind="actual", students=students
        )
    subjects = {
        "EIC": make_subject(plans["EIC"], coordination, "A1", p_hours="3"),
        "EEC": make_subject(plans["EEC"], coordination, "B1", p_hours="3"),
    }
    group = CrossCourseSubject.objects.create(name="Matemática")
    for subject in subjects.values():
        CrossCourseSubjectMember.objects.create(cross_course_subject=group, subject=subject)
    for course in courses.values():
        CrossCourseSubjectCourse.objects.create(cross_course_subject=group, course=course)
    manager = django_user_model.objects.create_user(username="m", password="x")
    RoleAssignment.objects.create(
        user=manager, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.FACULTY, scope_id=faculty.pk
    )
    coordinator = django_user_model.objects.create_user(username="c", password="x")
    RoleAssignment.objects.create(
        user=coordinator,
        profile=Profile.COORDINATOR,
        scope_kind=ScopeKind.COORDINATION,
        scope_id=coordination.pk,
    )
    dsd = create_dsd(years[2026], manager)
    semester = dsd.semesters.get(number=1)
    generate_offerings(manager, [semester])
    Room.objects.create(
        building="Edifício 9", number="101", room_type=RoomType.objects.first(), capacity=80
    )
    change_state(manager, "open", [semester], [coordination])
    return {
        "manager": manager,
        "coordinator": coordinator,
        "faculty": faculty,
        "coordination": coordination,
        "other_coordination": other_coordination,
        "years": years,
        "courses": courses,
        "plans": plans,
        "turmas": turmas,
        "subjects": subjects,
        "group": group,
        "semester": semester,
        "dsd": dsd,
        "links": {
            name: OfferingClassGroup.objects.get(class_group=turma)
            for name, turma in turmas.items()
        },
        "T": ClassType.objects.get(code="T"),
        "P": ClassType.objects.get(code="P"),
    }


def unit_of(world, course, class_type="T"):
    """The whole-turma unit of a course's turma for a class type."""
    return TeachingUnit.objects.get(
        members__class_group_link=world["links"][course], class_type=world[class_type]
    )


def group_unit(world, course, number, class_type="P"):
    """The unit of one group of a course's turma."""
    return TeachingUnit.objects.get(
        members__subgroup__class_group_link=world["links"][course],
        members__subgroup__number=number,
        class_type=world[class_type],
    )


def names(unit):
    """The members of a unit as ``course:turma`` strings."""
    result = []
    for member in unit.members.all():
        link = member.turma_link
        label = member.subgroup.label if member.subgroup_id else str(link.class_group)
        result.append(f"{link.class_group.course.name}|{label}")
    return sorted(result)


# --- allowed merges ----------------------------------------------------------------------------


def test_two_whole_turmas_of_different_courses_merge(world):
    """The EIC and EEC turmas share the theory class (30 + 24 = 54 students)."""
    host = merge_units(world["coordinator"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 54)
    assert len(names(host)) == 2 and {n.split("|")[0] for n in names(host)} == {"EIC", "EEC"}
    assert not TeachingUnit.objects.filter(pk=unit_of(world, "EEC").pk).exclude(pk=host.pk).exists()


def test_groups_of_different_courses_merge_into_one(world):
    """A group of EIC (15) and a group of EEC (12) become one unit of 27."""
    for course in ("EIC", "EEC"):
        set_group_count(world["coordinator"], world["links"][course], world["P"], 2)
    host = merge_units(
        world["coordinator"], [group_unit(world, "EIC", 1), group_unit(world, "EEC", 1)], 27
    )
    assert len(names(host)) == 2
    assert TeachingUnit.objects.filter(class_type=world["P"]).count() == 3  # was 4 groups


def test_a_whole_turma_and_a_group_of_another_course_merge(world):
    """A small undivided EEC turma joins a group of EIC."""
    set_group_count(world["coordinator"], world["links"]["EIC"], world["P"], 2)
    host = merge_units(
        world["coordinator"], [group_unit(world, "EIC", 2), unit_of(world, "EEC", "P")], 40
    )
    assert len(names(host)) == 2


def test_the_merge_is_not_stale_and_the_generator_leaves_it_alone(world):
    """A valid cross-course merge is not flagged and nothing is recreated."""
    host = merge_units(world["coordinator"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 54)
    assert host.pk not in stale_unit_ids(world["semester"], world["coordination"].pk)
    result = generate_offerings(world["manager"], [world["semester"]])
    assert result.created_units == 0 and result.stale_units == 0


# --- blocking rules ----------------------------------------------------------------------------


def test_subjects_that_are_not_transversal_do_not_merge(world):
    """A subject outside the group is a different subject: no merge between courses."""
    plan = world["plans"]["EEC"]
    make_subject(plan, world["coordination"], "B2")
    generate_offerings(world["manager"], [world["semester"]])
    foreign = TeachingUnit.objects.get(
        offering__subject__code="B2",
        class_type=world["T"],
        members__class_group_link__class_group=world["turmas"]["EEC"],
    )
    with pytest.raises(ValidationError) as error:
        merge_units(world["coordinator"], [unit_of(world, "EIC"), foreign], 54)
    assert "transversa" in error.value.messages[0]


def test_subjects_of_two_different_transversal_groups_do_not_merge(world):
    """Each group is its own subject: A1 (group 1) and B3 (group 2) are not one class."""
    other_group = CrossCourseSubject.objects.create(name="Física")
    extra_eic = make_subject(world["plans"]["EIC"], world["coordination"], "A3")
    extra_eec = make_subject(world["plans"]["EEC"], world["coordination"], "B3")
    for subject in (extra_eic, extra_eec):
        CrossCourseSubjectMember.objects.create(cross_course_subject=other_group, subject=subject)
    for course in world["courses"].values():
        CrossCourseSubjectCourse.objects.create(cross_course_subject=other_group, course=course)
    generate_offerings(world["manager"], [world["semester"]])
    foreign = TeachingUnit.objects.get(
        offering__subject=extra_eec,
        class_type=world["T"],
        members__class_group_link__class_group=world["turmas"]["EEC"],
    )
    with pytest.raises(ValidationError) as error:
        merge_units(world["coordinator"], [unit_of(world, "EIC"), foreign], 54)
    assert "mesmo grupo" in error.value.messages[0]


def test_a_course_that_is_not_indicated_does_not_merge(world):
    """EEC leaves the indicated courses: its turma cannot join EIC any more."""
    CrossCourseSubjectCourse.objects.filter(
        cross_course_subject=world["group"], course=world["courses"]["EEC"]
    ).delete()
    with pytest.raises(ValidationError) as error:
        merge_units(world["coordinator"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 54)
    assert "indicado" in error.value.messages[0]


def test_a_member_whose_plan_is_no_longer_in_force_does_not_merge(world):
    """D48: a new EEC plan reaches the first year in 2026 and the old subject stops counting."""
    StudyPlan.objects.create(course=world["courses"]["EEC"], academic_year=world["years"][2026])
    with pytest.raises(ValidationError):
        merge_units(world["coordinator"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 54)


def test_units_of_different_coordinations_do_not_merge(world):
    """Q8 by default: no merge between coordinations."""
    world["subjects"]["EEC"].coordination = world["other_coordination"]
    world["subjects"]["EEC"].save()
    with pytest.raises(ValidationError) as error:
        merge_units(world["coordinator"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 54)
    assert "coordena" in error.value.messages[0].lower()


def test_units_of_different_semesters_do_not_merge(world):
    """Units of the 1st and the 2nd semester are not one class."""
    second = make_subject(world["plans"]["EEC"], world["coordination"], "B1S2", semester=2)
    CrossCourseSubjectMember.objects.create(cross_course_subject=world["group"], subject=second)
    generate_offerings(world["manager"], [world["dsd"].semesters.get(number=2)])
    other = TeachingUnit.objects.get(offering__subject=second, class_type=world["T"])
    with pytest.raises(ValidationError) as error:
        merge_units(world["manager"], [unit_of(world, "EIC"), other], 54)
    assert "semestre" in error.value.messages[0]


# --- different weekly load ---------------------------------------------------------------------


def test_the_load_differences_are_listed_per_subject(world):
    """Same T hours: nothing; different P hours: both subjects with their hours."""
    assert merge_load_differences([unit_of(world, "EIC"), unit_of(world, "EEC")]) == {}
    SubjectClassLoad.objects.filter(subject=world["subjects"]["EEC"], class_type=world["P"]).update(
        weekly_hours="2"
    )
    differences = merge_load_differences([unit_of(world, "EIC", "P"), unit_of(world, "EEC", "P")])
    assert differences == {"A1": Decimal("3.00"), "B1": Decimal("2.00")}


def test_a_different_load_needs_the_confirmation(world):
    """Without the tick the merge is refused and says which hours differ."""
    SubjectClassLoad.objects.filter(subject=world["subjects"]["EEC"], class_type=world["P"]).update(
        weekly_hours="2"
    )
    units = [unit_of(world, "EIC", "P"), unit_of(world, "EEC", "P")]
    with pytest.raises(ValidationError) as error:
        merge_units(world["coordinator"], units, 54)
    assert "carga" in error.value.messages[0].lower()
    assert len(names(TeachingUnit.objects.get(pk=units[0].pk))) == 1


def test_a_confirmed_different_load_merges_and_counts_under_the_chosen_host(world):
    """The coordinator confirms and chooses the EEC unit: the hours are EEC's subject's."""
    SubjectClassLoad.objects.filter(subject=world["subjects"]["EEC"], class_type=world["P"]).update(
        weekly_hours="2"
    )
    eic, eec = unit_of(world, "EIC", "P"), unit_of(world, "EEC", "P")
    host = merge_units(world["coordinator"], [eic, eec], 54, accept_load_difference=True, host=eec)
    assert host.pk == eec.pk and host.offering.subject == world["subjects"]["EEC"]
    assert len(names(host)) == 2


# --- after the merge ---------------------------------------------------------------------------


def test_the_merge_becomes_stale_when_the_course_is_no_longer_indicated(world):
    """The manager removes EEC from the indicated courses: the merge is flagged, kept."""
    host = merge_units(world["coordinator"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 54)
    CrossCourseSubjectCourse.objects.filter(
        cross_course_subject=world["group"], course=world["courses"]["EEC"]
    ).delete()
    assert host.pk in stale_unit_ids(world["semester"], world["coordination"].pk)
    result = generate_offerings(world["manager"], [world["semester"]])
    assert result.stale_units == 1 and TeachingUnit.objects.filter(pk=host.pk).exists()


def test_separating_a_guest_gives_the_unit_back_to_its_own_offering(world):
    """The EEC turma leaves the merge: its new unit belongs to the EEC offering."""
    host = merge_units(world["coordinator"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 54)
    guest = host.members.get(class_group_link=world["links"]["EEC"])
    new = separate_member(world["coordinator"], host, guest, reason="separate courses")
    assert new.offering == world["links"]["EEC"].offering
    assert names(TeachingUnit.objects.get(pk=host.pk)) == [f"EIC|{world['turmas']['EIC']}"]
    assert generate_offerings(world["manager"], [world["semester"]]).created_units == 0


def test_the_last_own_member_of_the_host_cannot_leave_while_guests_remain(world):
    """The unit must keep a turma of its own offering."""
    host = merge_units(world["coordinator"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 54)
    own = host.members.get(class_group_link=world["links"]["EIC"])
    with pytest.raises(ValidationError) as error:
        separate_member(world["coordinator"], host, own, reason="x")
    assert "outros cursos" in error.value.messages[0]


def test_the_number_of_groups_of_a_guest_turma_can_grow(world):
    """A guest turma is divided in its own offering, in the same cell."""
    for course in ("EIC", "EEC"):
        set_group_count(world["coordinator"], world["links"][course], world["P"], 2)
    merge_units(
        world["coordinator"], [group_unit(world, "EIC", 1), group_unit(world, "EEC", 1)], 27
    )
    set_group_count(world["coordinator"], world["links"]["EEC"], world["P"], 3, "more labs")
    assert (
        TeachingUnit.objects.filter(
            members__subgroup__class_group_link=world["links"]["EEC"]
        ).count()
        == 3
    )
