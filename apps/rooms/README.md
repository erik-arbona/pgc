# rooms

**Responsibility:** rooms (functional block 8): building, number, type and capacity, entered by Património.

**Main models:**
- `RoomType` (configurable by Património; Sala de aula, Laboratório and Auditório are loaded by migration 0002).
- `Room` (building, number, optional name, type, capacity > 0; unique location ignoring case; `version` optimistic lock from `core.VersionedModel`). University-wide, no Faculty. See D63.
- Screens for Património: rooms (`/rooms/rooms/`, filtered with HTMX by type, minimum capacity and building; the form carries the `version`) and room types (`/rooms/types/`). The lookup for the other profiles (`/rooms/summary/`, permission `room.view` for the coordinator, Consulta and Património) shows how many rooms exist of each type and capacity, filtered by type and minimum capacity, with quantities only; `services.room_summary` is also what the exam module will use to warn when no room fits a group (D64).

**Permissions:** `room.edit` and `room_type.edit`, Património (`facilities`) only; `room.view` is read-only; that profile has no scope and is granted by the operator command.

**Dependencies:** `core`.
