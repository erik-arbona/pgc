# dsd

**Responsibility:** the DSD module (functional block 6, load calculation and validations). For now only pure domain rules; the models (DSD, offerings, teaching units, assignments) arrive with the phase 2 tasks T2.1 onwards.

**Rules (pure Python, no Django):**
- `teaching_hours.semester_teaching_hours` – weekly and semester teaching hours of each teacher: weekly hours of the class type x the teacher's share / 100, summed. A merged class is one teaching unit and counts once; each group is one unit, so N groups count N times. Exact `Decimal` arithmetic, no rounding. Returns the lines that explain each number and the share total of each unit for the alerts. See D70.

**Dependencies:** none yet (the Django adapter will use `academic`, `staff` and `core.parameters`).
