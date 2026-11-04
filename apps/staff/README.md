# staff

**Responsibility:** teachers (functional block 2): category, positions, and hour ranges with validity dates.

**Main models:**
- `Category` (scientific degree; Licenciado, Mestre and Doutor loaded by migration 0002) and `Position` (cargo; no initial data), both configurable.
- `Teacher` (University-wide unique identifier, ignoring case; coordination; category; type: full-time, habitual collaborator or competition teacher; active). The account link is a `core.RoleAssignment` of kind teacher (D38); a teacher with such a role cannot be deleted.
- `TeacherPosition` (positions held; only full-time teachers can have them).
- `load_ranges.py`: pure rule `resolve_load_range(rules, teacher, as_of)` for the annual range of lesson hours (lowest maximum wins; validity dates; per category, position and teacher type). `LoadRange` stores one rule (category, position or teacher type; min/max hours; `valid_from`) with database checks: exactly the reference of its kind, no type range for full-time teachers, minimum within the maximum and required except for teacher types, and one rule per subject and start date (no overlaps). `LoadRange.to_rule()` feeds the domain function. `services.load_range_for` / `load_ranges_for` (fixed number of queries) resolve the range of one or many teachers; `save_load_range` and `delete_load_range` write through the audit log, refuse rules already in force (a correction is a newer rule), refuse a change of subject and overlaps, and give Portuguese messages for inconsistent hours. Screens follow in the next parts of T3.2. See D58.

**Screens (PGC manager area):** categories (`/staff/categories/`) and positions (`/staff/positions/`): list, create, edit/deactivate (reason required) and delete when unused, with the generic views of `core.generic` (D50).

Teachers (`/staff/teachers/`; the form also edits the positions of full-time teachers through `services.save_teacher_with_positions`, one audit entry per row): scoped to the manager's Faculties through the teacher's coordination (D51), filtered with HTMX by coordination, type and activity; deleting a teacher audits their position assignments first (`services.delete_teacher`).

**Permissions:** `teacher.edit` (scoped to the Faculty of the teacher's coordination), `position.edit`, `category.edit`, `load_range.edit` (no scope: ranges are University-wide); PGC manager only. See D56.

**Dependencies:** `core`, `academic` (coordination).
