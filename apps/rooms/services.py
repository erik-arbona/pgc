"""Services of ``rooms``: the lookup by type and capacity.

Implements: docs/especificacao/02_perfis_e_dados.md – the coordinator sees how many rooms exist of
each type and capacity; 03_requisitos_funcionais.md – block 8; D64. The summary carries
quantities only: it never exposes the building, number or name of a room.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count

from .models import Room


@dataclass(frozen=True)
class RoomSummaryRow:
    """How many rooms exist of one type and capacity.

    Attributes:
        room_type_id: id of the room type.
        room_type_name: name of the room type.
        capacity: number of places.
        rooms: how many rooms have that type and capacity.
    """

    room_type_id: int
    room_type_name: str
    capacity: int
    rooms: int


def room_summary(
    room_type_id: int | None = None, min_capacity: int | None = None
) -> list[RoomSummaryRow]:
    """Count the rooms of each type and capacity.

    Rooms of a deactivated type are counted too: deactivating a type only stops new rooms from
    using it. The same function lets the exam module warn when no room fits a group (phase 2).

    Args:
        room_type_id: keep only this room type.
        min_capacity: keep only rooms that hold at least this many students.

    Returns:
        One row per type and capacity, ordered by the type's position, name and capacity.
    """
    rooms = Room.objects.all()
    if room_type_id is not None:
        rooms = rooms.filter(room_type_id=room_type_id)
    if min_capacity is not None:
        rooms = rooms.filter(capacity__gte=min_capacity)
    rows = (
        rooms.values("room_type_id", "room_type__name", "capacity")
        .annotate(rooms=Count("id"))
        .order_by("room_type__position", "room_type__name", "capacity")
    )
    return [
        RoomSummaryRow(
            room_type_id=row["room_type_id"],
            room_type_name=row["room_type__name"],
            capacity=row["capacity"],
            rooms=row["rooms"],
        )
        for row in rows
    ]
