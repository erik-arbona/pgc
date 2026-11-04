# academic

**Responsibility:** academic structure (functional block 1): faculty, coordination, course, academic year, study plan, subject, lesson types and classes.

**Main models:**
- `Faculty` (unique code), `Coordination` (belongs to one Faculty, name unique per Faculty), `Course` (Faculty + name + level; bachelor/master/doctorate) and `AcademicYear` (start year only). See D42.
- Planned: study plan and subject (T2.2), lesson types (T2.3), cross-course subjects (T2.4), classes (T2.5).

**Notes:** `Faculty.pk` and `Coordination.pk` are what `core.RoleAssignment.scope_id` refers to. All writes should use `core.audit.audited_save`.

**Dependencies:** `core`.
