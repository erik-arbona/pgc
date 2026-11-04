# academic

**Responsibility:** academic structure (functional block 1): faculty, coordination, course, academic year, study plan, subject, lesson types and classes.

**Main models:**
- `Faculty` (unique code), `Coordination` (belongs to one Faculty, name unique per Faculty), `Course` (Faculty + name + level; bachelor/master/doctorate) and `AcademicYear` (start year only). See D42.
- `StudyPlan` (course + starting academic year: plans are versioned per year), `Subject` (code unique per plan, ECTS, curricular year, semester 1/2, responsible coordination, semester hours), `ClassType` (configurable by the PGC manager: `is_active`, `position`; T, TP, P, L and OUT loaded by migration 0004; permission `class_type.edit`) and `SubjectClassLoad` (weekly hours per class type; `Subject.weekly_hours_total` sums them). See D44 and D45.
- Planned: cross-course subjects (T2.4), classes (T2.5).

**Notes:** `Faculty.pk` and `Coordination.pk` are what `core.RoleAssignment.scope_id` refers to. All writes should use `core.audit.audited_save`.

**Dependencies:** `core`.
