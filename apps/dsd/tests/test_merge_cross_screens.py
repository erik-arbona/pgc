"""Tests for the screens that merge units of different courses (T3.4b).

Implements: docs/backlog_fase2.md T3.4; D92 (cross-course merges: transversal subjects, indicated
courses, host chosen by the coordinator, confirmation when the weekly load differs), D91 (screens),
D86 (buttons only to who can write the cell).
"""

from decimal import Decimal

import pytest
from django.urls import reverse

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
from apps.dsd.models import Offering, OfferingClassGroup, TeachingUnit
from apps.dsd.services import (
    change_state,
    create_dsd,
    generate_offerings,
    merge_units,
    set_group_count,
)
from apps.rooms.models import Room, RoomType

pytestmark = pytest.mark.django_db


def make_subject(plan, coordination, code, p_hours="3"):
    """A first-year, first-semester subject with T (2 h) and P loads."""
    subject = Subject.objects.create(
        study_plan=plan,
        code=code,
        name=f"Disciplina {code}",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
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
    """EIC (A1, turma 30) and EEC (B1, turma 24) share a transversal subject; big room."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2026)}
    courses, plans, turmas, subjects = {}, {}, {}, {}
    for name, students in (("EIC", 30), ("EEC", 24)):
        courses[name] = Course.objects.create(faculty=faculty, name=name, level="bachelor")
        plans[name] = StudyPlan.objects.create(course=courses[name], academic_year=years[2023])
        turmas[name] = ClassGroup.objects.create(
            course=courses[name], intake_year=years[2026], study_plan=plans[name], label="X"
        )
        Enrollment.objects.create(
            class_group=turmas[name], academic_year=years[2026], kind="actual", students=students
        )
        subjects[name] = make_subject(plans[name], coordination, "A1" if name == "EIC" else "B1")
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
    other = django_user_model.objects.create_user(username="o", password="x")
    RoleAssignment.objects.create(
        user=other,
        profile=Profile.COORDINATOR,
        scope_kind=ScopeKind.COORDINATION,
        scope_id=Coordination.objects.create(faculty=faculty, name="Coordenação B").pk,
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
        "other": other,
        "coordination": coordination,
        "courses": courses,
        "plans": plans,
        "turmas": turmas,
        "subjects": subjects,
        "group": group,
        "semester": semester,
        "offerings": {
            name: Offering.objects.get(subject=subject) for name, subject in subjects.items()
        },
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


def page_url(world, course):
    """The page of a course's offering."""
    return reverse("dsd:offering_detail", args=[world["offerings"][course].pk])


def merge_url(world, course, *units):
    """The merge page, opened from a course's offering, for some units."""
    query = "&".join(f"units={unit.pk}" for unit in units)
    return f"{reverse('dsd:offering_merge', args=[world['offerings'][course].pk])}?{query}"


def merge_post(client, world, course, units, capacity=54, **extra):
    """Post the merge form from a course's offering."""
    data = {
        "units": [u.pk for u in units],
        "room_capacity": capacity,
        "seen": ",".join(f"{u.pk}:{u.version}" for u in units),
        "host": units[0].pk,
        **extra,
    }
    return client.post(reverse("dsd:offering_merge", args=[world["offerings"][course].pk]), data)


def set_eec_p_hours(world, hours):
    """Give the EEC subject a different weekly load for P."""
    SubjectClassLoad.objects.filter(subject=world["subjects"]["EEC"], class_type=world["P"]).update(
        weekly_hours=hours
    )


# --- the "other courses" section ---------------------------------------------------------------


def test_the_page_offers_the_units_of_the_other_courses_to_who_can_write(client, world):
    """On the EIC page the coordinator can select the EEC units of the transversal subject."""
    client.force_login(world["coordinator"])
    page = client.get(page_url(world, "EIC")).content.decode()
    assert "Outros cursos" in page and "Disciplina B1" in page
    assert f'value="{unit_of(world, "EEC").pk}"' in page


def test_the_section_is_empty_without_write_access_or_a_transversal_partner(client, world):
    """No checkboxes for the other coordination's coordinator; nothing if not transversal."""
    client.force_login(world["other"])
    assert "Outros cursos" not in client.get(page_url(world, "EIC")).content.decode()
    CrossCourseSubjectCourse.objects.filter(
        cross_course_subject=world["group"], course=world["courses"]["EEC"]
    ).delete()
    client.force_login(world["coordinator"])
    assert "Disciplina B1" not in client.get(page_url(world, "EIC")).content.decode()


# --- the merge page ----------------------------------------------------------------------------


def test_the_merge_page_accepts_units_of_the_partner_offering(client, world):
    """EIC T + EEC T: both listed, sum 54, host choices are the two units."""
    client.force_login(world["coordinator"])
    response = client.get(merge_url(world, "EIC", unit_of(world, "EIC"), unit_of(world, "EEC")))
    assert response.status_code == 200 and response.context["students"] == 54
    host_field = response.context["form"].fields["host"]
    assert {str(choice[0]) for choice in host_field.choices} == {
        str(unit_of(world, "EIC").pk),
        str(unit_of(world, "EEC").pk),
    }


def test_the_merge_page_warns_about_a_different_load_and_asks_to_confirm(client, world):
    """P hours 3 vs 2: both subjects with their hours and the confirmation box."""
    set_eec_p_hours(world, "2")
    client.force_login(world["coordinator"])
    response = client.get(
        merge_url(world, "EIC", unit_of(world, "EIC", "P"), unit_of(world, "EEC", "P"))
    )
    page = response.content.decode()
    assert response.context["load_differences"] == {"A1": Decimal("3.00"), "B1": Decimal("2.00")}
    assert "A1" in page and "B1" in page and "accept_load_difference" in page


def test_the_merge_page_has_no_confirmation_box_when_the_load_is_the_same(client, world):
    """T is 2 h in both: no warning and no box."""
    client.force_login(world["coordinator"])
    response = client.get(merge_url(world, "EIC", unit_of(world, "EIC"), unit_of(world, "EEC")))
    assert response.context["load_differences"] == {}
    assert "accept_load_difference" not in response.content.decode()


def test_the_coordinator_merges_two_courses_from_the_form(client, world):
    """Posting the units with the first as host merges and keeps it."""
    client.force_login(world["coordinator"])
    units = [unit_of(world, "EIC"), unit_of(world, "EEC")]
    response = merge_post(client, world, "EIC", units)
    assert response.status_code == 302
    host = TeachingUnit.objects.get(pk=units[0].pk)
    assert host.members.count() == 2 and not TeachingUnit.objects.filter(pk=units[1].pk).exists()


def test_the_chosen_host_is_the_unit_that_stays(client, world):
    """Choosing the EEC unit as host keeps the EEC offering's unit."""
    client.force_login(world["coordinator"])
    units = [unit_of(world, "EIC"), unit_of(world, "EEC")]
    merge_post(client, world, "EIC", units, host=units[1].pk)
    assert TeachingUnit.objects.get(pk=units[1].pk).members.count() == 2
    assert not TeachingUnit.objects.filter(pk=units[0].pk).exists()


def test_a_different_load_without_the_confirmation_shows_the_error(client, world):
    """The merge is refused and nothing changes."""
    set_eec_p_hours(world, "2")
    client.force_login(world["coordinator"])
    units = [unit_of(world, "EIC", "P"), unit_of(world, "EEC", "P")]
    response = merge_post(client, world, "EIC", units)
    assert response.status_code == 200 and "Carga semanal" in response.content.decode()
    assert TeachingUnit.objects.get(pk=units[0].pk).members.count() == 1


def test_a_different_load_with_the_confirmation_merges(client, world):
    """Ticking the box accepts the difference."""
    set_eec_p_hours(world, "2")
    client.force_login(world["coordinator"])
    units = [unit_of(world, "EIC", "P"), unit_of(world, "EEC", "P")]
    response = merge_post(client, world, "EIC", units, accept_load_difference="on")
    assert response.status_code == 302
    assert TeachingUnit.objects.get(pk=units[0].pk).members.count() == 2


def test_a_unit_of_another_semester_is_not_found(client, world):
    """Only units of this DSD semester can be put together here."""
    second = world["semester"].dsd.semesters.get(number=2)
    later = make_subject(world["plans"]["EIC"], world["coordination"], "A2")
    later.semester = 2
    later.save()
    generate_offerings(world["manager"], [second])
    other_semester_unit = TeachingUnit.objects.get(offering__subject=later, class_type=world["T"])
    client.force_login(world["coordinator"])
    url = merge_url(world, "EIC", unit_of(world, "EIC"), other_semester_unit)
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("who", ["other"])
def test_others_get_403_on_a_cross_course_merge(client, world, who):
    """The other coordination's coordinator cannot merge."""
    units = [unit_of(world, "EIC"), unit_of(world, "EEC")]
    client.force_login(world[who])
    assert client.get(merge_url(world, "EIC", *units)).status_code == 403
    assert merge_post(client, world, "EIC", units).status_code == 403


# --- the guest offering and the buttons --------------------------------------------------------


def merged(world):
    """EIC and EEC merged for T with the EIC unit as host."""
    return merge_units(world["coordinator"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 54)


def test_the_guest_offering_page_says_where_its_turma_was_merged(client, world):
    """On the EEC page: merged in A1 of EIC, with the link to separate it."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["EEC"])
    client.force_login(world["coordinator"])
    page = client.get(page_url(world, "EEC")).content.decode()
    assert "Juntada em" in page and "A1" in page
    separate = reverse(
        "dsd:offering_separate", args=[world["offerings"]["EIC"].pk, host.pk, member.pk]
    )
    assert separate in page


def test_separating_from_the_guest_page_link_works(client, world):
    """Following that link and posting a reason gives the turma back its own unit."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["EEC"])
    client.force_login(world["coordinator"])
    url = reverse("dsd:offering_separate", args=[world["offerings"]["EIC"].pk, host.pk, member.pk])
    response = client.post(url, {"reason": "separate", "seen": host.version})
    assert response.status_code == 302
    assert TeachingUnit.objects.filter(offering=world["offerings"]["EEC"]).count() == 2


def test_the_groups_button_of_a_guest_turma_points_at_its_own_offering(client, world):
    """In the host page the guest group's button uses the guest offering (it used to 404)."""
    for course in ("EIC", "EEC"):
        set_group_count(world["coordinator"], world["links"][course], world["P"], 2)
    first = TeachingUnit.objects.get(
        members__subgroup__class_group_link=world["links"]["EIC"], members__subgroup__number=1
    )
    second = TeachingUnit.objects.get(
        members__subgroup__class_group_link=world["links"]["EEC"], members__subgroup__number=1
    )
    merge_units(world["coordinator"], [first, second], 30)
    client.force_login(world["coordinator"])
    page = client.get(page_url(world, "EIC")).content.decode()
    guest_url = reverse(
        "dsd:offering_groups",
        args=[world["offerings"]["EEC"].pk, world["links"]["EEC"].pk, world["P"].pk],
    )
    assert guest_url in page
    assert client.get(guest_url).status_code == 200


def test_a_partner_of_another_coordination_is_not_offered(client, world):
    """The other course's subject is run by another coordination: no merge, so no checkbox."""
    other = Coordination.objects.exclude(pk=world["coordination"].pk).first()
    world["subjects"]["EEC"].coordination = other
    world["subjects"]["EEC"].save()
    client.force_login(world["coordinator"])
    assert "Disciplina B1" not in client.get(page_url(world, "EIC")).content.decode()


def test_a_merge_inside_the_same_offering_is_not_listed_as_merged_elsewhere(client, world):
    """Two EIC turmas merged together are not "Juntada em" another offering."""
    second = ClassGroup.objects.create(
        course=world["courses"]["EIC"],
        intake_year=world["turmas"]["EIC"].intake_year,
        study_plan=world["plans"]["EIC"],
        label="Y",
    )
    Enrollment.objects.create(
        class_group=second,
        academic_year=world["turmas"]["EIC"].intake_year,
        kind="actual",
        students=10,
    )
    generate_offerings(world["manager"], [world["semester"]])
    second_unit = TeachingUnit.objects.get(
        class_type=world["T"], members__class_group_link__class_group=second
    )
    merge_units(world["coordinator"], [unit_of(world, "EIC"), second_unit], 40)
    client.force_login(world["coordinator"])
    assert "Juntada em" not in client.get(page_url(world, "EIC")).content.decode()


def test_the_guest_page_has_no_separate_link_without_write_access(client, world):
    """After the closing the page still says where the turma is, but offers no way to separate."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["EEC"])
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="done"
    )
    client.force_login(world["coordinator"])
    page = client.get(page_url(world, "EEC")).content.decode()
    separate = reverse(
        "dsd:offering_separate", args=[world["offerings"]["EIC"].pk, host.pk, member.pk]
    )
    assert "Juntada em" in page and separate not in page
