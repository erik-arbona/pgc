"""Tests for rooms, room types and the shared optimistic lock.

Implements: docs/especificacao/02_perfis_e_dados.md – rooms entered by Património (location,
name when it has one, type and capacity); 07_arquitetura.md / CLAUDE.md – optimistic lock on
rooms; D07, D63.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.core.audit import audited_save
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.core.permissions import can
from apps.rooms.models import Room, RoomType

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab():
    """The laboratory room type loaded by the migration."""
    return RoomType.objects.get(code="LAB")


def make_room(room_type, building="Edifício 9", number="101", capacity=27, **overrides):
    """Create a room."""
    data = dict(building=building, number=number, room_type=room_type, capacity=capacity)
    data.update(overrides)
    return Room.objects.create(**data)


def test_the_room_types_named_by_the_user_are_loaded_by_the_migration():
    """Sala de aula, Laboratório and Auditório exist after migrating, in this order (D63)."""
    assert list(RoomType.objects.values_list("name", flat=True)) == [
        "Sala de aula",
        "Laboratório",
        "Auditório",
    ]


def test_a_new_room_type_can_be_added():
    """The list is configurable: Património adds the types it needs ('etc.')."""
    assert RoomType.objects.create(code="SEM", name="Sala de seminários").is_active


def test_a_room_has_a_location_an_optional_name_a_type_and_a_capacity(lab):
    """The example of the specification: Edifício 9, sala 101, 27 places."""
    room = make_room(lab)
    assert (room.building, room.number, room.name, room.capacity) == ("Edifício 9", "101", "", 27)
    named = make_room(lab, number="Anf", name="Anfiteatro Magno", capacity=200)
    assert named.name == "Anfiteatro Magno"


def test_the_location_is_unique_ignoring_case(lab):
    """The same building and number cannot be entered twice, whatever the letter case."""
    make_room(lab, building="Edifício 9", number="a12")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_room(lab, building="EDIFÍCIO 9", number="A12")


def test_the_same_number_may_exist_in_another_building(lab):
    """Uniqueness is per building."""
    make_room(lab, building="Edifício 9", number="101")
    make_room(lab, building="Edifício 3", number="101")
    assert Room.objects.count() == 2


@pytest.mark.parametrize("capacity", [0, -1])
def test_the_capacity_must_be_positive(lab, capacity):
    """A room holds at least one student."""
    with pytest.raises(IntegrityError), transaction.atomic():
        make_room(lab, capacity=capacity)


def test_a_room_type_in_use_cannot_be_deleted(lab):
    """Rooms keep their type alive."""
    make_room(lab)
    with pytest.raises(ProtectedError):
        lab.delete()


def test_room_type_code_and_name_are_unique(lab):
    """Catalogue entries are not duplicated."""
    with pytest.raises(IntegrityError), transaction.atomic():
        RoomType.objects.create(code="LAB", name="Outro")
    with pytest.raises(IntegrityError), transaction.atomic():
        RoomType.objects.create(code="L2", name="Laboratório")


def test_a_room_starts_at_version_one_and_each_save_adds_one(lab):
    """The optimistic lock (CLAUDE.md): the version grows with every save."""
    room = make_room(lab)
    assert room.version == 1
    room.capacity = 30
    room.save()
    assert Room.objects.get(pk=room.pk).version == 2


def test_saving_with_a_stale_version_is_refused(lab):
    """Two editors: the second one, with the old version, cannot overwrite the first."""
    room = make_room(lab)
    first, second = Room.objects.get(pk=room.pk), Room.objects.get(pk=room.pk)
    first.capacity = 30
    first.save()
    second.capacity = 40
    with pytest.raises(ValidationError):
        second.save()
    assert Room.objects.get(pk=room.pk).capacity == 30


def test_a_stale_save_through_the_audit_function_writes_no_entry(lab):
    """A refused save leaves no audit entry."""
    actor = get_user_model().objects.create_user(username="patrimonio")
    room = make_room(lab)
    stale = Room.objects.get(pk=room.pk)
    room.capacity = 30
    audited_save(room, actor, "Medida")
    before = AuditEntry.objects.count()
    stale.capacity = 50
    with pytest.raises(ValidationError):
        audited_save(stale, actor, "Outro")
    assert AuditEntry.objects.count() == before


@pytest.mark.parametrize("profile", list(Profile))
def test_only_facilities_edit_rooms_and_room_types(profile):
    """Património alone; no scope is needed because rooms are University-wide (D07, D63)."""
    user = get_user_model().objects.create_user(username="u", password="x")
    kind = {
        Profile.PGC_MANAGER: ScopeKind.FACULTY,
        Profile.COORDINATOR: ScopeKind.COORDINATION,
        Profile.EXECUTIVE_BOARD: ScopeKind.FACULTY,
        Profile.TEACHER: ScopeKind.TEACHER,
    }.get(profile, ScopeKind.NONE)
    RoleAssignment.objects.create(
        user=user, profile=profile, scope_kind=kind, scope_id=None if kind == "none" else 999_999
    )
    expected = profile == Profile.FACILITIES
    assert can(user, "room.edit") is expected
    assert can(user, "room_type.edit") is expected
