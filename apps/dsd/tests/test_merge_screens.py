"""Tests for the screens that merge and separate teaching units (T3.3b).

Implements: docs/backlog_fase2.md T3.3; D91 (merge rules and room request), D64 (the coordinator
sees room quantities, never a room; the manager has no room access), D86 (buttons only to who can
write the cell), D54 (versions the user saw).
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


def user_with(django_user_model, profile, kind, scope_id, username):
    """A user with one role."""
    user = django_user_model.objects.create_user(username=username, password="x")
    RoleAssignment.objects.create(user=user, profile=profile, scope_kind=kind, scope_id=scope_id)
    return user


@pytest.fixture
def world(django_user_model):
    """A DSD of 2026 with turmas A (30) and B (25), a subject with T and P, one 60-place room."""
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
    Room.objects.create(
        building="Edifício 9", number="101", room_type=RoomType.objects.first(), capacity=60
    )
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
        "offering": Offering.objects.get(),
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


def page_url(world):
    """The page of the offering."""
    return reverse("dsd:offering_detail", args=[world["offering"].pk])


def merge_url(world, *units):
    """The merge page for some units."""
    query = "&".join(f"units={unit.pk}" for unit in units)
    return f"{reverse('dsd:offering_merge', args=[world['offering'].pk])}?{query}"


def merge_post(client, world, units, capacity=55, seen=None, **extra):
    """Post the merge form."""
    seen = ",".join(f"{u.pk}:{u.version}" for u in units) if seen is None else seen
    return client.post(
        reverse("dsd:offering_merge", args=[world["offering"].pk]),
        {"units": [u.pk for u in units], "room_capacity": capacity, "seen": seen, **extra},
    )


def merged(world):
    """A and B merged for T, asked for a room of 55."""
    open_cell(world)
    return merge_units(world["coordinator"], [unit_of(world, "A"), unit_of(world, "B")], 55)


# --- the buttons on the offering page ----------------------------------------------------------


def test_the_page_has_a_checkbox_per_unit_for_who_can_write(client, world):
    """In an open cell the coordinator can select units to merge."""
    open_cell(world)
    client.force_login(world["coordinator"])
    page = client.get(page_url(world)).content.decode()
    assert 'name="units"' in page and "Juntar selecionadas" in page
    assert page.count('name="units"') == TeachingUnit.objects.count()


def test_the_page_has_no_checkboxes_without_write_access(client, world):
    """Not opened for the coordinator, or another coordination: nothing to select."""
    client.force_login(world["coordinator"])
    assert 'name="units"' not in client.get(page_url(world)).content.decode()
    open_cell(world)
    client.force_login(world["other_coordinator"])
    assert 'name="units"' not in client.get(page_url(world)).content.decode()


def test_an_obsolete_unit_has_no_checkbox(client, world):
    """The load of T leaves the subject: its T units are obsolete and cannot be selected."""
    open_cell(world)
    SubjectClassLoad.objects.filter(
        subject=world["offering"].subject, class_type=world["T"]
    ).delete()
    client.force_login(world["coordinator"])
    page = client.get(page_url(world)).content.decode()
    assert page.count('name="units"') == TeachingUnit.objects.filter(class_type=world["P"]).count()


def test_a_merged_unit_offers_to_separate_each_member(client, world):
    """One 'Separar' link per member of the merge."""
    host = merged(world)
    client.force_login(world["coordinator"])
    page = client.get(page_url(world)).content.decode()
    for member in host.members.all():
        assert (
            reverse("dsd:offering_separate", args=[world["offering"].pk, host.pk, member.pk])
            in page
        )
    assert page.count("Separar") >= 2


def test_the_change_groups_button_survives_a_merged_group(client, world):
    """Group 1 of A is merged with a group of B: its 'Alterar n.º de grupos' is still offered."""
    open_cell(world)
    for label in ("A", "B"):
        set_group_count(world["manager"], world["links"][label], world["P"], 2)
    first = TeachingUnit.objects.get(
        members__subgroup__class_group_link=world["links"]["A"], members__subgroup__number=1
    )
    second = TeachingUnit.objects.get(
        members__subgroup__class_group_link=world["links"]["B"], members__subgroup__number=1
    )
    merge_units(world["coordinator"], [first, second], 30)
    client.force_login(world["coordinator"])
    page = client.get(page_url(world)).content.decode()
    groups_url = reverse(
        "dsd:offering_groups", args=[world["offering"].pk, world["links"]["A"].pk, world["P"].pk]
    )
    assert groups_url in page


def test_the_page_shows_the_room_request_of_a_merge(client, world):
    """The capacity asked is visible on the unit."""
    merged(world)
    client.force_login(world["coordinator"])
    assert "55" in client.get(page_url(world)).content.decode()


# --- the merge page ----------------------------------------------------------------------------


def test_the_merge_page_lists_the_members_and_the_sum(client, world):
    """30 + 25 = 55 students, suggested as the room capacity."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = client.get(merge_url(world, unit_of(world, "A"), unit_of(world, "B")))
    assert response.status_code == 200
    assert response.context["students"] == 55
    assert response.context["form"].initial["room_capacity"] == 55


def test_the_coordinator_sees_room_quantities_the_manager_does_not(client, world):
    """D64: the quantities go to who may read them, and never a room location."""
    open_cell(world)
    units = (unit_of(world, "A"), unit_of(world, "B"))
    client.force_login(world["coordinator"])
    page = client.get(merge_url(world, *units)).content.decode()
    assert "Edifício 9" not in page and response_has_rooms(page)
    client.force_login(world["manager"])
    assert not response_has_rooms(client.get(merge_url(world, *units)).content.decode())


def response_has_rooms(page):
    """Whether the page shows the table of room quantities."""
    return "Salas disponíveis" in page


def test_the_merge_page_with_less_than_two_units_goes_back_with_a_message(client, world):
    """One unit is not a merge: back to the offering."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = client.get(merge_url(world, unit_of(world, "A")))
    assert response.status_code == 302 and response["Location"] == page_url(world)


def test_the_merge_page_shows_a_missing_enrollment(client, world):
    """Without the number of students the page says so instead of guessing."""
    open_cell(world)
    Enrollment.objects.filter(class_group=world["links"]["B"].class_group).delete()
    client.force_login(world["coordinator"])
    page = client.get(merge_url(world, unit_of(world, "A"), unit_of(world, "B"))).content.decode()
    assert "matrícula" in page


def test_the_coordinator_merges_from_the_form(client, world):
    """Posting the units and the room asked merges them and saves the request."""
    open_cell(world)
    units = [unit_of(world, "A"), unit_of(world, "B")]
    client.force_login(world["coordinator"])
    response = merge_post(client, world, units, capacity=55)
    assert response.status_code == 302 and response["Location"] == page_url(world)
    host = TeachingUnit.objects.get(pk=units[0].pk)
    assert host.members.count() == 2 and host.room_capacity == 55
    assert not TeachingUnit.objects.filter(pk=units[1].pk).exists()


def test_a_room_asked_that_cannot_hold_the_students_shows_the_error(client, world):
    """40 places for 55 students: the form comes back with the message."""
    open_cell(world)
    units = [unit_of(world, "A"), unit_of(world, "B")]
    client.force_login(world["coordinator"])
    response = merge_post(client, world, units, capacity=40)
    assert response.status_code == 200 and "55" in response.content.decode()
    assert TeachingUnit.objects.get(pk=units[0].pk).members.count() == 1


def test_no_room_in_the_campus_blocks_the_merge_with_a_message(client, world):
    """Asking for 70 places when the biggest room has 60."""
    open_cell(world)
    units = [unit_of(world, "A"), unit_of(world, "B")]
    client.force_login(world["coordinator"])
    response = merge_post(client, world, units, capacity=70)
    assert response.status_code == 200 and "Nenhuma sala" in response.content.decode()


def test_a_stale_form_is_refused_with_a_message(client, world):
    """Someone else changed one of the units after the form was loaded."""
    open_cell(world)
    units = [unit_of(world, "A"), unit_of(world, "B")]
    seen = ",".join(f"{u.pk}:{u.version}" for u in units)
    TeachingUnit.objects.filter(pk=units[0].pk).update(version=units[0].version + 1)
    client.force_login(world["coordinator"])
    response = merge_post(client, world, units, seen=seen)
    assert response.status_code == 200
    assert "alterado por outra pessoa" in response.content.decode()


def test_a_unit_of_another_offering_in_the_request_is_not_found(client, world):
    """Only the units of the offering in the URL can be merged here."""
    open_cell(world)
    client.force_login(world["coordinator"])
    url = f"{reverse('dsd:offering_merge', args=[world['offering'].pk])}?units=999999&units=999998"
    assert client.get(url).status_code == 404


def test_a_unit_of_another_offering_opens_but_is_refused_when_not_transversal(client, world):
    """T3.4: units of other offerings can be put together, but only transversal subjects merge."""
    open_cell(world)
    other = Subject.objects.create(
        study_plan=world["offering"].subject.study_plan,
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
    foreign = TeachingUnit.objects.filter(offering__subject=other).first()
    client.force_login(world["coordinator"])
    units = [unit_of(world, "A"), foreign]
    assert client.get(merge_url(world, *units)).status_code == 200
    response = merge_post(client, world, units)
    assert response.status_code == 200 and "transversais" in response.content.decode()
    assert TeachingUnit.objects.get(pk=units[0].pk).members.count() == 1


@pytest.mark.parametrize("who", ["other_coordinator", "teacher"])
def test_others_get_403_on_the_merge_page(client, world, who):
    """Not the coordinator of the coordination, not the manager of the Faculty."""
    open_cell(world)
    units = [unit_of(world, "A"), unit_of(world, "B")]
    client.force_login(world[who])
    assert client.get(merge_url(world, *units)).status_code == 403
    assert merge_post(client, world, units).status_code == 403
    assert TeachingUnit.objects.get(pk=units[0].pk).members.count() == 1


def test_anonymous_visitors_are_redirected_to_login(client, world):
    """The merge and separate pages require a session."""
    response = client.get(merge_url(world, unit_of(world, "A"), unit_of(world, "B")))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


# --- the separate page -------------------------------------------------------------------------


def separate_url(world, host, member):
    """The separate page of a member."""
    return reverse("dsd:offering_separate", args=[world["offering"].pk, host.pk, member.pk])


def test_the_coordinator_separates_a_member_from_the_form(client, world):
    """The member gets a unit of its own and the merge keeps the rest."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["B"])
    client.force_login(world["coordinator"])
    response = client.post(
        separate_url(world, host, member), {"reason": "rooms changed", "seen": host.version}
    )
    assert response.status_code == 302 and response["Location"] == page_url(world)
    assert TeachingUnit.objects.get(pk=host.pk).members.count() == 1
    assert TeachingUnit.objects.filter(class_type=world["T"]).count() == 2


def test_separating_without_a_reason_shows_an_error(client, world):
    """D40: undoing a merge needs a reason."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["B"])
    client.force_login(world["coordinator"])
    response = client.post(separate_url(world, host, member), {"reason": "", "seen": host.version})
    assert response.status_code == 200
    assert TeachingUnit.objects.get(pk=host.pk).members.count() == 2


def test_separating_with_a_stale_version_shows_the_message(client, world):
    """The unit changed after the form was loaded."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["B"])
    client.force_login(world["coordinator"])
    response = client.post(
        separate_url(world, host, member), {"reason": "x", "seen": host.version - 1}
    )
    assert response.status_code == 200
    assert "alterado por outra pessoa" in response.content.decode()


@pytest.mark.parametrize("who", ["other_coordinator", "teacher"])
def test_others_get_403_on_the_separate_page(client, world, who):
    """Same permission as merging."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["B"])
    client.force_login(world[who])
    assert client.get(separate_url(world, host, member)).status_code == 403
    assert client.post(separate_url(world, host, member), {"reason": "x"}).status_code == 403
    assert TeachingUnit.objects.get(pk=host.pk).members.count() == 2


def test_a_member_of_another_unit_in_the_url_is_not_found(client, world):
    """The member must belong to the unit in the URL."""
    host = merged(world)
    other_member = unit_of(world, "A", "P").members.get()
    client.force_login(world["coordinator"])
    assert client.get(separate_url(world, host, other_member)).status_code == 404


def test_a_separate_post_without_the_version_is_refused(client, world):
    """The version of the merged unit is part of the form."""
    host = merged(world)
    member = host.members.get(class_group_link=world["links"]["B"])
    client.force_login(world["coordinator"])
    response = client.post(separate_url(world, host, member), {"reason": "x"})
    assert response.status_code == 200
    assert TeachingUnit.objects.get(pk=host.pk).members.count() == 2


def test_a_merge_post_without_the_versions_is_refused(client, world):
    """The versions of the units are part of the form."""
    open_cell(world)
    units = [unit_of(world, "A"), unit_of(world, "B")]
    client.force_login(world["coordinator"])
    response = client.post(
        reverse("dsd:offering_merge", args=[world["offering"].pk]),
        {"units": [u.pk for u in units], "room_capacity": 55},
    )
    assert response.status_code == 200
    assert TeachingUnit.objects.get(pk=units[0].pk).members.count() == 1
