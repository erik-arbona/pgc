# academic

**Responsibility:** academic structure (functional block 1): faculty, coordination, course, academic year, study plan, subject, lesson types and classes.

**Main models:**
- `Faculty` (unique code), `Coordination` (belongs to one Faculty, name unique per Faculty), `Course` (Faculty + name + level; bachelor/master/doctorate) and `AcademicYear` (start year only). See D42.
- `StudyPlan` (course + starting academic year: plans are versioned per year), `Subject` (code unique per plan, ECTS, curricular year, semester 1/2, responsible coordination, semester hours), `ClassType` (configurable by the PGC manager: `is_active`, `position`; T, TP, P, L and OUT loaded by migration 0004; permission `class_type.edit`) and `SubjectClassLoad` (weekly hours per class type; `Subject.weekly_hours_total` sums them). See D44, D45, D47 and D48. `plans.plan_in_force` says which study plan serves a curricular year in an academic year; `services.effective_group_members` applies it to cross-course groups.
- `CrossCourseSubject` + `CrossCourseSubjectMember` (a subject is in at most one group) + `CrossCourseSubjectCourse` (courses where classes may be merged, D22); `Subject.programme`. Rules (group checks, semester/load warnings) are pure functions in `cross_course.py`; `services.facts_for` adapts a `Subject`. Permission `cross_course_subject.edit`. See D47.
- Planned: classes (T2.5).

**Notes:** `Faculty.pk` and `Coordination.pk` are what `core.RoleAssignment.scope_id` refers to. All writes should use `core.audit.audited_save`.

**Dependencies:** `core`.
