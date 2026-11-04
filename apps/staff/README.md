# staff

**Responsibility:** teachers (functional block 2): category, positions, and hour ranges with validity dates.

**Main models:**
- `Category` (scientific degree; Licenciado, Mestre and Doutor loaded by migration 0002) and `Position` (cargo; no initial data), both configurable.
- `Teacher` (University-wide unique identifier, ignoring case; coordination; category; type: full-time, habitual collaborator or competition teacher; active). The account link is a `core.RoleAssignment` of kind teacher (D38); a teacher with such a role cannot be deleted.
- `TeacherPosition` (positions held; only full-time teachers can have them).
- Planned: hours ranges by category, position and type (T3.2).

**Permissions:** `teacher.edit` (scoped to the Faculty of the teacher's coordination), `position.edit`, `category.edit`; PGC manager only. See D56.

**Dependencies:** `core`, `academic` (coordination).
