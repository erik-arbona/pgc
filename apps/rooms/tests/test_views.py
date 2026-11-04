"""View tests for the room and room type screens (T4.1, part 2).

Implements: docs/especificacao/02_perfis_e_dados.md – Património enters the rooms; D07, D40, D50,
D59, D63. Only Património reaches these screens; the version in the form is the optimistic lock.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import AuditEntry, Profile
from apps.rooms.models import Room, RoomType

pytestmark = pytest.mark.django_db


@pytest.fixture
def facilities_client(client, make_user):
    """A client logged in as Património."""
    client.force_login(make_user(Profile.FACILITIES, "patrimonio"))
    return client


@pytest.fixture
def lab():
    """The laboratory room type."""
    return RoomType.objects.get(code="LAB")


def make_room(room_type, building="Edifício 9", number="101", capacity=27, **overrides):
    """Create a room."""
    data = dict(building=building, number=number, room_type=room_type, capacity=capacity)
    data.update(overrides)
    return Room.objects.create(**data)


def room_data(room_type, **overrides):
    """POST data for the room form."""
    data = {
        "building": "Edifício 3",
        "number": "205",
        "name": "",
        "room_type": room_type.pk,
        "capacity": 40,
        "reason": "",
    }
    data.update(overrides)
    return data


ALL_URLS = [
    ("rooms:room_list", False),
    ("rooms:room_create", False),
    ("rooms:roomtype_list", False),
    ("rooms:roomtype_create", False),
]


def test_anonymous_visitors_are_redirected_to_login(client):
    """The lists require a session."""
    for name in ("rooms:room_list", "rooms:roomtype_list"):
        response = client.get(reverse(name))
        assert response.status_code == 302 and "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.FACILITIES])
def test_only_facilities_reach_the_screens(client, make_user, lab, profile):
    """Every other profile, the PGC manager included, gets 403 on GET and POST (D07)."""
    room = make_room(lab)
    client.force_login(make_user(profile))
    urls = [
        reverse("rooms:room_list"),
        reverse("rooms:room_create"),
        reverse("rooms:room_update", kwargs={"pk": room.pk}),
        reverse("rooms:room_delete", kwargs={"pk": room.pk}),
        reverse("rooms:roomtype_list"),
        reverse("rooms:roomtype_create"),
        reverse("rooms:roomtype_update", kwargs={"pk": lab.pk}),
        reverse("rooms:roomtype_delete", kwargs={"pk": lab.pk}),
    ]
    for url in urls:
        assert client.get(url).status_code == 403
        assert client.post(url, room_data(lab) | {"reason": "x"}).status_code == 403
    assert Room.objects.count() == 1 and not AuditEntry.objects.exists()


def test_a_superuser_without_assignment_gets_403(client):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse("rooms:room_list")).status_code == 403


# --- rooms ------------------------------------------------------------------------------------


def test_the_list_shows_the_rooms_with_their_type_and_capacity(facilities_client, lab):
    """Location, name, type and capacity appear."""
    make_room(lab, name="Laboratório de Redes", capacity=27)
    page = facilities_client.get(reverse("rooms:room_list")).content.decode()
    assert "Edifício 9" in page and "101" in page and "Laboratório de Redes" in page
    assert "27" in page


def test_the_list_filters_by_type_capacity_and_building(facilities_client, lab):
    """The filters narrow the list."""
    aud = RoomType.objects.get(code="AUD")
    make_room(lab, building="Edifício 9", number="L1", capacity=20)
    make_room(aud, building="Edifício 3", number="A1", capacity=200)
    url = reverse("rooms:room_list")
    page = facilities_client.get(url, {"room_type": aud.pk}).content.decode()
    assert "A1" in page and ">L1<" not in page
    page = facilities_client.get(url, {"min_capacity": 100}).content.decode()
    assert ">A1<" in page and ">L1<" not in page
    page = facilities_client.get(url, {"building": "edifício 9"}).content.decode()
    assert ">L1<" in page and ">A1<" not in page


def test_an_htmx_request_returns_only_the_results(facilities_client, lab):
    """With the HX-Request header the list is a fragment; without it, the full page."""
    make_room(lab)
    url = reverse("rooms:room_list")
    fragment = facilities_client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "101" in fragment and "<html" not in fragment
    assert "htmx" in facilities_client.get(url).content.decode()


def test_the_list_is_paginated(facilities_client, lab):
    """More than 25 rooms spill onto page 2."""
    for i in range(30):
        make_room(lab, number=f"N{i:02d}")
    url = reverse("rooms:room_list")
    assert len(facilities_client.get(url).context["object_list"]) == 25
    assert len(facilities_client.get(url + "?page=2").context["object_list"]) == 5


def test_creating_a_room_is_audited_and_needs_no_reason(facilities_client, lab):
    """The creation leaves one entry with the actor."""
    response = facilities_client.post(reverse("rooms:room_create"), room_data(lab))
    room = Room.objects.get()
    assert response.status_code == 302
    entry = AuditEntry.objects.get(entity="rooms.room")
    assert (entry.action, entry.entity_id, entry.actor.username) == (
        "create",
        str(room.pk),
        "patrimonio",
    )


def test_a_duplicate_location_is_a_message_in_portuguese(facilities_client, lab):
    """The same building and number, whatever the case, is refused with a clear message."""
    make_room(lab, building="Edifício 3", number="a1")
    response = facilities_client.post(
        reverse("rooms:room_create"), room_data(lab, building="EDIFÍCIO 3", number="A1")
    )
    assert response.status_code == 200
    assert "Já existe uma sala" in " ".join(response.context["form"].non_field_errors())
    assert Room.objects.count() == 1


@pytest.mark.parametrize("capacity", ["0", "-5", "abc"])
def test_an_invalid_capacity_is_a_form_error(facilities_client, lab, capacity):
    """The capacity must be a positive number."""
    response = facilities_client.post(
        reverse("rooms:room_create"), room_data(lab, capacity=capacity)
    )
    assert response.status_code == 200
    assert "capacity" in response.context["form"].errors
    assert not Room.objects.exists()


def test_an_inactive_room_type_is_not_offered_for_a_new_room(facilities_client, lab):
    """Deactivated types are not given to new rooms."""
    old = RoomType.objects.create(code="OLD", name="Antigo", is_active=False)
    response = facilities_client.post(reverse("rooms:room_create"), room_data(old))
    assert response.status_code == 200 and "room_type" in response.context["form"].errors


def test_the_form_carries_the_version_and_a_stale_one_is_refused(facilities_client, lab):
    """Two editors: the second, with the old version, cannot overwrite the first."""
    room = make_room(lab)
    url = reverse("rooms:room_update", kwargs={"pk": room.pk})
    shown = facilities_client.get(url).context["form"].initial["version"]
    assert shown == room.version
    other = Room.objects.get(pk=room.pk)
    other.capacity = 99
    other.save()
    stale = facilities_client.post(
        url, room_data(lab, building=room.building, number=room.number, version=shown, reason="x")
    )
    assert stale.status_code == 200 and stale.context["form"].non_field_errors()
    assert Room.objects.get(pk=room.pk).capacity == 99


def test_updating_needs_a_reason_and_is_audited(facilities_client, lab):
    """No reason: refused. With a preset: changed, with old and new values."""
    room = make_room(lab)
    url = reverse("rooms:room_update", kwargs={"pk": room.pk})
    data = room_data(lab, building=room.building, number=room.number, capacity=30, version=1)
    facilities_client.post(url, data)
    room.refresh_from_db()
    assert room.capacity == 27 and not AuditEntry.objects.exists()
    facilities_client.post(url, {**data, "reason_choice": "data_update"})
    room.refresh_from_db()
    assert (room.capacity, room.version) == (30, 2)
    entry = AuditEntry.objects.get(entity="rooms.room", action="update")
    assert (entry.old_value["capacity"], entry.new_value["capacity"]) == (27, 30)


def test_deleting_a_room_needs_a_reason_and_is_audited(facilities_client, lab):
    """Deletion asks for a reason and is logged."""
    room = make_room(lab)
    url = reverse("rooms:room_delete", kwargs={"pk": room.pk})
    facilities_client.post(url, {})
    assert Room.objects.exists()
    facilities_client.post(url, {"reason_choice": "created_by_mistake"})
    assert not Room.objects.exists()
    assert AuditEntry.objects.get(entity="rooms.room").action == "delete"


# --- room types ----------------------------------------------------------------------------------


def test_the_room_type_list_shows_the_initial_types(facilities_client):
    """Sala de aula, Laboratório and Auditório are listed."""
    page = facilities_client.get(reverse("rooms:roomtype_list")).content.decode()
    assert all(name in page for name in ("Sala de aula", "Laboratório", "Auditório"))


def test_creating_a_room_type_is_audited(facilities_client):
    """Património adds the types it needs."""
    facilities_client.post(
        reverse("rooms:roomtype_create"),
        {"code": "SEM", "name": "Sala de seminários", "position": 40, "is_active": "on"},
    )
    assert RoomType.objects.filter(code="SEM").exists()
    assert AuditEntry.objects.get(entity="rooms.roomtype").action == "create"


def test_a_duplicate_room_type_is_a_form_error(facilities_client, lab):
    """Code and name are unique."""
    response = facilities_client.post(
        reverse("rooms:roomtype_create"),
        {"code": "LAB", "name": "Outro", "position": 1, "is_active": "on"},
    )
    assert response.status_code == 200 and "code" in response.context["form"].errors


def test_deactivating_a_room_type_needs_a_reason(facilities_client, lab):
    """Unchecking 'active' is an update and asks for a reason."""
    url = reverse("rooms:roomtype_update", kwargs={"pk": lab.pk})
    data = {"code": "LAB", "name": "Laboratório", "position": 20}
    facilities_client.post(url, data)
    lab.refresh_from_db()
    assert lab.is_active
    facilities_client.post(url, {**data, "reason_choice": "data_update"})
    lab.refresh_from_db()
    assert not lab.is_active


def test_deleting_a_room_type_in_use_shows_a_message(facilities_client, lab):
    """A type that a room uses is kept; nothing is audited."""
    make_room(lab)
    response = facilities_client.post(
        reverse("rooms:roomtype_delete", kwargs={"pk": lab.pk}),
        {"reason_choice": "data_update"},
        follow=True,
    )
    assert RoomType.objects.filter(pk=lab.pk).exists()
    assert "em uso" in response.content.decode()
    assert not AuditEntry.objects.exists()


def test_deleting_an_unused_room_type_is_audited(facilities_client):
    """An unused type can be deleted with a reason."""
    aud = RoomType.objects.get(code="AUD")
    facilities_client.post(
        reverse("rooms:roomtype_delete", kwargs={"pk": aud.pk}), {"reason_choice": "data_update"}
    )
    assert not RoomType.objects.filter(pk=aud.pk).exists()
    assert AuditEntry.objects.get(entity="rooms.roomtype").action == "delete"


def test_menu_shows_the_links_to_património(facilities_client):
    """Rooms and room types appear in the menu of Património."""
    page = facilities_client.get("/").content.decode()
    assert reverse("rooms:room_list") in page and reverse("rooms:roomtype_list") in page
