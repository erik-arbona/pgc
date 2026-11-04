# dsd

**Responsibility:** the DSD module (functional block 6, load calculation and validations). For now only pure domain rules; the models (DSD, offerings, teaching units, assignments) arrive with the phase 2 tasks T2.1 onwards.

**Rules (pure Python, no Django):**
- `teaching_hours.semester_teaching_hours` – weekly and semester teaching hours of each teacher: weekly hours of the class type x the teacher's share / 100, summed. A merged class is one teaching unit and counts once; each group is one unit, so N groups count N times. Exact `Decimal` arithmetic on the lines; only the totals of a teacher are rounded to two decimals, half up (D73). Returns the lines that explain each number and the share total of each unit for the alerts. See D70.
- `preparation.teacher_preparation_hours` / `preparation_by_teacher` – weekly preparation hours of each teacher: the weights per class type (`academic.preparation`) applied to the teacher's weekly hours, so preparation follows each lesson hour (repeated per group, per share). See D71.
- `annual_load.annual_teaching_hours` / `annual_load` – annual weekly teaching hours (sum of the two semesters, with each semester kept) joined with the range in force on a reference date given by the caller (`staff.load_ranges.resolve_load_range`). The four states and the extra hours come next. See D72.
- `load_status.assess_load` – the state of the annual load (below the minimum, in the range, at the maximum, above the maximum, or no range) and the extra hours (total minus the maximum above it), from the annual load. See D74.

**Dependencies:** `academic.preparation` and `staff.load_ranges` (pure functions); nothing else yet (the Django adapter will use `academic`, `staff` and `core.parameters`).
