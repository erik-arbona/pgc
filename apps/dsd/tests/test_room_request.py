"""Tests for the room request of a teaching unit and its warnings (T3.5).

Implements: docs/backlog_fase2.md T3.5; Q9 (the request is per teaching unit), D64 (the coordinator
sees quantities only), D86 (state of the cell), D40 (reason when changing), D54 (versions). The
request is a capacity and, optionally, a room type; a unit warns when no room of the campus fits
or when the room asked is smaller than its students. Merging keeps blocking (D91).
"""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
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
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.dsd.models import Offering, OfferingClassGroup, TeachingUnit
from apps.dsd.services import (
    change_state,
    create_dsd,
    generate_offerings,
    room_request_warnings,
    set_group_count,
    set_room_request,
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
    """One turma of 30 students, a subject with T and P, a 40-place classroom and a lab of 20."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    other = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2026)}
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="EIC", level="bachelor"),
        academic_year=years[2023],
    )
    manager = user_with(django_user_model, Profile.PGC_MANAGER, ScopeKind.FACULTY, faculty.pk, "m")
    turma = ClassGroup.objects.create(
        course=plan.course, intake_year=years[2026], study_plan=plan, label="A"
    )
    Enrollment.objects.create(
        class_group=turma, academic_year=years[2026], kind="actual", students=30
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
    classroom, lab = RoomType.objects.get(code="SALA"), RoomType.objects.get(code="LAB")
    Room.objects.create(building="Edifício 9", number="101", room_type=classroom, capacity=40)
    Room.objects.create(building="Edifício 9", number="LAB1", room_type=lab, capacity=20)
    return {
        "manager": manager,
        "coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, coordination.pk, "c"
        ),
        "other": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, other.pk, "o"
        ),
        "teacher": user_with(django_user_model, Profile.TEACHER, ScopeKind.NONE, None, "t"),
        "semester": semester,
        "coordination": coordination,
        "offering": Offering.objects.get(),
        "link": OfferingClassGroup.objects.get(),
        "classroom": classroom,
        "lab": lab,
        "T": ClassType.objects.get(code="T"),
        "P": ClassType.objects.get(code="P"),
    }


def open_cell(world):
    """Open the semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def unit(world, class_type="T"):
    """The unit of the turma for a class type, as stored."""
    return TeachingUnit.objects.get(offering=world["offering"], class_type=world[class_type])


# --- the service -------------------------------------------------------------------------------


def test_the_coordinator_asks_for_a_room_of_a_capacity(world):
    """35 places, any type: saved on the unit."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 35, None)
    saved = unit(world)
    assert (saved.room_capacity, saved.room_type) == (35, None)


def test_the_request_can_name_a_room_type(world):
    """A laboratory for the practical class."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world, "P"), 20, world["lab"])
    assert unit(world, "P").room_type == world["lab"]


def test_the_first_request_needs_no_reason_but_leaves_one_in_the_audit(world):
    """D40: a default reason is recorded."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 35, None)
    entry = AuditEntry.objects.filter(entity="dsd.teachingunit", action="update").latest("pk")
    assert entry.actor == world["coordinator"] and entry.reason.strip()
    assert entry.new_value["room_capacity"] == 35 and entry.old_value["room_capacity"] is None


def test_changing_or_clearing_the_request_needs_a_reason(world):
    """Once there is a request, changes need a reason."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 35, None)
    for capacity in (36, None):
        with pytest.raises(ValidationError):
            set_room_request(world["coordinator"], unit(world), capacity, None, reason=" ")
    assert unit(world).room_capacity == 35
    set_room_request(world["coordinator"], unit(world), None, None, reason="no room needed")
    assert unit(world).room_capacity is None


def test_the_same_request_writes_nothing(world):
    """No change: no version bump and no audit entry."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 35, world["classroom"])
    before = (unit(world).version, AuditEntry.objects.count())
    set_room_request(world["coordinator"], unit(world), 35, world["classroom"])
    assert (unit(world).version, AuditEntry.objects.count()) == before


@pytest.mark.parametrize("capacity", [0, -3])
def test_the_capacity_must_be_positive(world, capacity):
    """Zero or negative places make no sense."""
    open_cell(world)
    with pytest.raises(ValidationError):
        set_room_request(world["coordinator"], unit(world), capacity, None)
    assert unit(world).room_capacity is None


def test_a_room_type_without_capacity_is_refused(world):
    """The type alone does not say how many places."""
    open_cell(world)
    with pytest.raises(ValidationError):
        set_room_request(world["coordinator"], unit(world), None, world["lab"])


def test_a_stale_version_is_refused(world):
    """Someone else changed the unit after it was loaded (D54)."""
    open_cell(world)
    seen = unit(world).version
    set_room_request(world["manager"], unit(world), 30, None)
    with pytest.raises(ValidationError) as error:
        set_room_request(world["coordinator"], unit(world), 35, None, reason="x", seen_version=seen)
    assert "alterado por outra pessoa" in error.value.messages[0]
    assert unit(world).room_capacity == 30


def test_the_coordinator_cannot_ask_before_the_cell_is_opened_but_the_manager_can(world):
    """Not opened: only the manager prepares (D86)."""
    with pytest.raises(ValidationError):
        set_room_request(world["coordinator"], unit(world), 35, None)
    set_room_request(world["manager"], unit(world), 35, None)
    assert unit(world).room_capacity == 35


def test_nobody_asks_in_a_closed_cell(world):
    """Closed is read-only."""
    open_cell(world)
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="done"
    )
    for who in ("coordinator", "manager"):
        with pytest.raises(ValidationError):
            set_room_request(world[who], unit(world), 35, None, reason="x")


@pytest.mark.parametrize("who", ["other", "teacher"])
def test_only_who_covers_the_coordination_asks(world, who):
    """Another coordination's coordinator, or a teacher, is denied."""
    open_cell(world)
    with pytest.raises(PermissionDenied):
        set_room_request(world[who], unit(world), 35, None)


# --- the warnings ------------------------------------------------------------------------------


def test_a_request_that_fits_has_no_warning(world):
    """35 places for 30 students and a 40-place classroom exists."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 35, None)
    assert room_request_warnings(unit(world), 30) == []


def test_a_unit_without_request_has_no_warning(world):
    """Nothing asked, nothing to warn about."""
    assert room_request_warnings(unit(world), 30) == []


def test_no_room_of_the_campus_fits_warns(world):
    """100 places: the biggest room has 40."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 100, None)
    warnings = room_request_warnings(unit(world), 30)
    assert len(warnings) == 1 and "Nenhuma sala" in warnings[0]


def test_no_room_of_the_type_asked_warns(world):
    """A 35-place laboratory does not exist: the lab has 20."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world, "P"), 35, world["lab"])
    warnings = room_request_warnings(unit(world, "P"), 30)
    assert any("Nenhuma sala" in warning for warning in warnings)


def test_a_room_smaller_than_the_students_warns(world):
    """25 places for 30 students: a room exists, but it does not hold them."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 25, None)
    warnings = room_request_warnings(unit(world), 30)
    assert len(warnings) == 1 and "30" in warnings[0]


def test_the_warning_follows_the_rooms_of_the_campus(world):
    """If Património removes the big room the warning appears, with nothing saved."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 35, None)
    assert room_request_warnings(unit(world), 30) == []
    Room.objects.filter(room_type=world["classroom"]).delete()
    assert len(room_request_warnings(unit(world), 30)) == 1


def test_unknown_students_only_check_the_rooms(world):
    """Without the number of students only the existence of a room is checked."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 25, None)
    assert room_request_warnings(unit(world), None) == []


# --- the screens -------------------------------------------------------------------------------


def room_url(world, class_type="T"):
    """The room request form of a unit."""
    return reverse("dsd:unit_room", args=[world["offering"].pk, unit(world, class_type).pk])


def page_url(world):
    """The page of the offering."""
    return reverse("dsd:offering_detail", args=[world["offering"].pk])


def post(client, world, capacity, room_type="", reason="", class_type="T", seen=None):
    """Post the room request form."""
    return client.post(
        room_url(world, class_type),
        {
            "room_capacity": capacity,
            "room_type": room_type,
            "reason": reason,
            "seen": unit(world, class_type).version if seen is None else seen,
        },
    )


def test_the_form_suggests_the_students_of_the_unit(client, world):
    """30 students: 30 places suggested when there is no request yet."""
    open_cell(world)
    client.force_login(world["coordinator"])
    assert client.get(room_url(world)).context["form"].initial["room_capacity"] == 30


def test_the_coordinator_asks_from_the_form(client, world):
    """Posting capacity and type saves the request and goes back to the page."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = post(client, world, 35, room_type=world["classroom"].pk)
    assert response.status_code == 302 and response["Location"] == page_url(world)
    assert (unit(world).room_capacity, unit(world).room_type) == (35, world["classroom"])


def test_changing_without_a_reason_shows_an_error(client, world):
    """The form asks for the reason once there is a request."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 35, None)
    client.force_login(world["coordinator"])
    assert post(client, world, 36).status_code == 200
    assert unit(world).room_capacity == 35


def test_a_stale_form_shows_the_message(client, world):
    """The unit changed after the form was loaded."""
    open_cell(world)
    seen = unit(world).version
    set_room_request(world["manager"], unit(world), 30, None)
    client.force_login(world["coordinator"])
    response = post(client, world, 35, reason="x", seen=seen)
    assert response.status_code == 200
    assert "alterado por outra pessoa" in response.content.decode()


@pytest.mark.parametrize("who", ["other", "teacher"])
def test_others_get_403_on_the_room_form(client, world, who):
    """Same permission as the other unit edits."""
    open_cell(world)
    client.force_login(world[who])
    assert client.get(room_url(world)).status_code == 403
    assert post(client, world, 35).status_code == 403
    assert unit(world).room_capacity is None


def test_a_unit_of_another_offering_in_the_url_is_not_found(client, world):
    """The unit must belong to the offering in the URL."""
    open_cell(world)
    client.force_login(world["coordinator"])
    url = reverse("dsd:unit_room", args=[world["offering"].pk, unit(world).pk + 9999])
    assert client.get(url).status_code == 404


def test_a_real_unit_of_another_offering_in_the_url_is_not_found(client, world):
    """A unit that exists, but belongs to a different offering than the one in the URL."""
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
    url = reverse("dsd:unit_room", args=[world["offering"].pk, foreign.pk])
    assert client.get(url).status_code == 404


def test_anonymous_visitors_are_redirected_to_login(client, world):
    """The form requires a session."""
    response = client.get(room_url(world))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_the_page_offers_the_request_to_who_can_write(client, world):
    """'Pedir sala' for a unit without request, 'Alterar pedido de sala' with one."""
    open_cell(world)
    client.force_login(world["coordinator"])
    assert "Pedir sala" in client.get(page_url(world)).content.decode()
    set_room_request(world["coordinator"], unit(world), 35, None)
    page = client.get(page_url(world)).content.decode()
    assert "Alterar pedido de sala" in page and room_url(world) in page


def test_the_page_has_no_request_buttons_without_write_access(client, world):
    """Not opened for the coordinator: nothing to press."""
    client.force_login(world["coordinator"])
    assert room_url(world) not in client.get(page_url(world)).content.decode()


def test_the_page_shows_the_warnings_and_never_a_room(client, world):
    """A request no room can serve is flagged; no building or number is shown (D64)."""
    open_cell(world)
    set_room_request(world["coordinator"], unit(world), 100, None)
    client.force_login(world["coordinator"])
    page = client.get(page_url(world)).content.decode()
    assert "Nenhuma sala" in page and "Edifício 9" not in page


def test_a_divided_turma_asks_per_group_unit(client, world):
    """Each group is a unit of its own, so each can ask for its own room (Q9)."""
    open_cell(world)
    set_group_count(world["coordinator"], world["link"], world["P"], 2)
    first, second = TeachingUnit.objects.filter(
        offering=world["offering"], class_type=world["P"]
    ).order_by("pk")
    set_room_request(world["coordinator"], first, 20, world["lab"])
    set_room_request(world["coordinator"], second, 15, None)
    assert [
        u.room_capacity
        for u in TeachingUnit.objects.filter(
            offering=world["offering"], class_type=world["P"]
        ).order_by("pk")
    ] == [20, 15]
    # 30 students in 2 groups: 15 each, so 15 places hold a group.
    assert room_request_warnings(TeachingUnit.objects.get(pk=second.pk), 15) == []
