# demo

**Responsibility:** the command that loads the fictitious data set of `docs/dados_ficticios.md` (D65). No models.

**Command:** `docker compose exec web python manage.py load_demo_data`
- Creates 2 Faculties, 4 coordinations, 3 bachelor courses and 1 master with 2-year plans, 8 subjects per course (obeying the 15-week rule), one turma per course and two (A and B) in one course, the subject "Introdução à Programação" in 3 courses declared cross-course in 2, 8 teachers (every category and type, some with positions), test hour ranges, 6 rooms of 3 types (one tiny) and one account per profile.
- Safe to run twice (only creates what is missing), never deletes, writes through the audit log as the system.
- Refuses to run with `DEBUG` off unless `--force`; outside development the demo accounts have no password. In development the password is `demo1234`.

**Not covered yet (needs later phases):** assignments and the four load states, the 50/50 shared lesson type, the exam season and the enrolment lists.

**Dependencies:** `core`, `academic`, `staff`, `rooms`.

**Real study plans (D78, D80):** `manage.py load_real_plans` loads the plans of EIC and TM from `docs/Planos_EIC_TM.md` (courses, plans, tracks and 86 subjects). `real_plans.py` is the pure parser, `real_plan_loader.py` writes the records through the audited services; the command takes `--faculty` and `--coordination` or `--placeholders`, `--eic-year`, `--tm-year`, `--turmas` and `--force`. It is idempotent and lists what it does not load (the UCT tables and the optional subjects).

**DSD scenario (T8.1):** `dsd_loader.load_dsd_scenario` runs at the end of `DemoLoader.load`. It creates the DSD of the demo year with its offerings, opens the first semester, estimates the enrolments and gives the eight demo teachers eight different situations of the live load (four below the minimum with the four states of the reason, one in range, one at the maximum, two above it with extra hours accepted and not), plus two other activities. It goes through the same services as the screens, as `demo_gestor` and `demo_ce`, and each step only runs if its result is missing, so it never overrides what a person did. See D65.
