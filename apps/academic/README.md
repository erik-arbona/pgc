# academic

**Responsibility:** academic structure (functional block 1): faculty, coordination, course, academic year, study plan, subject, lesson types and classes.

**Main models:**
- `Faculty` (unique code), `Coordination` (belongs to one Faculty, name unique per Faculty), `Course` (Faculty + name + level; bachelor/master/doctorate) and `AcademicYear` (start year only). See D42.
- `StudyPlan` (course + starting academic year: plans are versioned per year), `Subject` (code unique per plan, ECTS, curricular year, semester 1/2, responsible coordination, semester hours), `ClassType` (configurable by the PGC manager: `is_active`, `position`; T, TP, P, L and OUT loaded by migration 0004; permission `class_type.edit`) and `SubjectClassLoad` (weekly hours per class type; `Subject.weekly_hours_total` sums them). See D44, D45, D47, D48 and D49. `plans.plan_in_force` says which study plan serves a curricular year in an academic year; `services.effective_group_members` applies it to cross-course groups.
- `CrossCourseSubject` + `CrossCourseSubjectMember` (a subject is in at most one group) + `CrossCourseSubjectCourse` (courses where classes may be merged, D22); `Subject.programme`. Rules (group checks, semester/load warnings) are pure functions in `cross_course.py`; `services.facts_for` adapts a `Subject`. Permission `cross_course_subject.edit`. See D47.
- `ClassGroup` (turma): a cohort with an intake academic year, optional label (empty when there is one), a study plan fixed at creation (D48) and an optional last academic year; its curricular year is computed (`class_groups.curricular_year_in`). `services.create_class_group` picks the plan in force for year 1. Permission `class_group.edit`. See D49.

**Notes:** `Faculty.pk` and `Coordination.pk` are what `core.RoleAssignment.scope_id` refers to. All writes should use `core.audit.audited_save`.

**Screens (PGC manager area, T2.6):** class types, Faculties, academic years, coordinations, courses, study plans (`/academic/study-plans/`) and turmas (`/academic/class-groups/`, optimistic lock on `ClassGroup.version`), subjects (`/academic/subjects/`, filtered with HTMX; the subject form also edits the weekly hours per class type through `services.save_subject_with_loads`) so far (`/academic/coordinations/` and `/academic/courses/` are limited to the manager's Faculties, D51; `/academic/class-types/`, `/academic/faculties/`, `/academic/academic-years/`; actions `class_type.edit`, `faculty.edit`, `academic_year.edit`); see `apps/core/generic.py` for the shared list/create/edit/delete views and D50.

**Dependencies:** `core`.
