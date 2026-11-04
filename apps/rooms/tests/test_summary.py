"""Tests for the room lookup by type and capacity (T4.2).

Implements: docs/especificacao/02_perfis_e_dados.md – the coordinator sees how many rooms exist of
each type and capacity; 03_requisitos_funcionais.md – block 8, lookup by type and capacity; D64.
Only quantities are shown: no building, number or name.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import Profile
from apps.core.permissions import can
from apps.rooms.models import Room, RoomType
from apps.rooms.services import RoomSummaryRow, room_summary

pytestmark = pytest.mark.django_db

ALLOWED = {Profile.COORDINATOR, Profile.VIEWER, Profile.FACILITIES}


@pytest.fixture
def types():
    """The three initial room types by code."""
    return {t.code: t for t in RoomType.objects.all()}


def make_rooms(types):
    """Three 27-seat laboratories, one 40-seat laboratory, two 30-seat classrooms."""
    for i in range(3):
        Room.objects.create(
            building="Edifício 9", number=f"L{i}", room_type=types["LAB"], capacity=27
        )
    Room.objects.create(building="Edifício 9", number="L9", room_type=types["LAB"], capacity=40)
    for i in range(2):
        Room.objects.create(
            building="Edifício 3", number=f"S{i}", room_type=types["SALA"], capacity=30
        )


def pairs(rows):
    """The (type name, capacity, rooms) triples of a summary."""
    return [(r.room_type_name, r.capacity, r.rooms) for r in rows]


# --- the summary --------------------------------------------------------------------------------


def test_the_summary_counts_rooms_by_type_and_capacity(types):
    """Rows follow the type order, then the capacity."""
    make_rooms(types)
    assert pairs(room_summary()) == [
        ("Sala de aula", 30, 2),
        ("Laboratório", 27, 3),
        ("Laboratório", 40, 1),
    ]


def test_the_summary_can_be_filtered_by_type(types):
    """Only the rows of one type."""
    make_rooms(types)
    assert pairs(room_summary(room_type_id=types["LAB"].pk)) == [
        ("Laboratório", 27, 3),
        ("Laboratório", 40, 1),
    ]


def test_the_summary_can_be_filtered_by_minimum_capacity(types):
    """Rooms that hold at least that many students."""
    make_rooms(types)
    assert pairs(room_summary(min_capacity=30)) == [
        ("Sala de aula", 30, 2),
        ("Laboratório", 40, 1),
    ]
    assert room_summary(min_capacity=41) == []


def test_rooms_of_an_inactive_type_are_still_counted(types):
    """Deactivating a type only stops new rooms from using it."""
    make_rooms(types)
    RoomType.objects.filter(code="LAB").update(is_active=False)
    assert sum(r.rooms for r in room_summary()) == 6


def test_an_empty_summary_has_no_rows():
    """No rooms, no rows."""
    assert room_summary() == []


def test_a_row_carries_quantities_only():
    """No building, number or name can leak through the summary."""
    assert set(RoomSummaryRow.__dataclass_fields__) == {
        "room_type_id",
        "room_type_name",
        "capacity",
        "rooms",
    }


# --- permission ---------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", list(Profile))
def test_who_can_view_rooms(make_user, profile):
    """The coordinator, Consulta and Património may; nobody else (D64)."""
    assert can(make_user(profile), "room.view") is (profile in ALLOWED)


def test_anonymous_visitors_are_redirected_to_login(client):
    """The screen requires a session."""
    response = client.get(reverse("rooms:summary"))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p not in ALLOWED])
def test_other_profiles_get_403(client, make_user, profile):
    """The Gestor, the Conselho Executivo, teachers and Serviços Académicos have no access."""
    client.force_login(make_user(profile))
    assert client.get(reverse("rooms:summary")).status_code == 403


def test_a_superuser_without_assignment_gets_403(client):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse("rooms:summary")).status_code == 403


# --- the screen ---------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", sorted(ALLOWED))
def test_allowed_profiles_see_the_quantities(client, make_user, types, profile):
    """Each row says how many rooms exist of a type and capacity."""
    make_rooms(types)
    client.force_login(make_user(profile))
    response = client.get(reverse("rooms:summary"))
    assert response.status_code == 200
    page = response.content.decode()
    assert "Laboratório" in page and "Sala de aula" in page


def test_the_coordinator_sees_no_individual_room_data(client, make_user, types):
    """Building, number and name of the rooms are not on the page."""
    Room.objects.create(
        building="Edifício Secreto",
        number="Z99",
        name="Anfiteatro Magno",
        room_type=types["AUD"],
        capacity=200,
    )
    client.force_login(make_user(Profile.COORDINATOR))
    page = client.get(reverse("rooms:summary")).content.decode()
    assert "Auditório" in page and "200" in page
    assert "Edifício Secreto" not in page and "Z99" not in page and "Magno" not in page


def test_the_screen_filters_by_type_and_capacity(client, make_user, types):
    """The filters narrow the table."""
    make_rooms(types)
    client.force_login(make_user(Profile.COORDINATOR))
    url = reverse("rooms:summary")
    page = client.get(url, {"room_type": types["SALA"].pk}).content.decode()
    assert "Sala de aula" in page and "<td>Laboratório</td>" not in page
    page = client.get(url, {"min_capacity": 40}).content.decode()
    assert "<td>Laboratório</td>" in page and "<td>Sala de aula</td>" not in page


def test_an_htmx_request_returns_only_the_results(client, make_user, types):
    """With the HX-Request header the screen is a fragment; without it, the full page."""
    make_rooms(types)
    client.force_login(make_user(Profile.COORDINATOR))
    url = reverse("rooms:summary")
    assert "<html" not in client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "htmx" in client.get(url).content.decode()


def test_the_menu_shows_the_link_to_the_coordinator_but_not_the_room_editor(client, make_user):
    """A coordinator gets the lookup, not the screens that edit rooms."""
    client.force_login(make_user(Profile.COORDINATOR))
    page = client.get("/").content.decode()
    assert reverse("rooms:summary") in page
    assert reverse("rooms:room_list") not in page
