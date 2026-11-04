# rooms

**Responsibility:** rooms (functional block 8): building, number, type and capacity, entered by Património.

**Main models:**
- `RoomType` (configurable by Património; Sala de aula, Laboratório and Auditório are loaded by migration 0002).
- `Room` (building, number, optional name, type, capacity > 0; unique location ignoring case; `version` optimistic lock from `core.VersionedModel`). University-wide, no Faculty. See D63.
- Planned: screens (T4.1 part 2) and the lookup by type and capacity (T4.2).

**Permissions:** `room.edit` and `room_type.edit`, Património (`facilities`) only; that profile has no scope and is granted by the operator command.

**Dependencies:** `core`.
