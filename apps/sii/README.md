# sii

**Responsibility:** the contract for importing data from the SII, and a CSV implementation to test it (T5.1, D66). No models and nothing is written to the database.

**The SII medium is still an open question** (API, database connection or CSV files; `docs/especificacao/09_criterios_e_questoes.md`), so the real connection is **not** implemented.

**Contract (`contract.py`):** `SiiSource` with `read_teachers()`, `read_enrollments()` and `read_exam_registrations()`, each returning a `ReadResult` (valid records plus `RowError`s with line and column, never the value: it is personal data). Another medium is another class with the same methods, chosen by `SII_SOURCE`.

**CSV test source (`csv_source.py`):** reads `teachers.csv`, `enrollments.csv` and `exam_registrations.csv` from the folder in `SII_CSV_DIR`. Accepts `,` or `;` and the UTF-8 byte order mark; ignores extra columns. Column names are provisional:

| File | Columns |
| --- | --- |
| `teachers.csv` | `identifier`, `name`, `category` |
| `enrollments.csv` | `student_number`, `course_ref`, `academic_year`, `curricular_year` |
| `exam_registrations.csv` | `student_number`, `student_name`, `subject_ref`, `season`, `academic_year`, `semester` |

**Command:** `docker compose exec web python manage.py sii_preview <folder>` prints counts and problems and saves nothing. Fictitious samples are in `samples/`.

**Not done (waits for the answers and for phase 2):** mapping SII course and subject references to PGC records, saving enrolments, teachers and exam registrations, and the export of the teacher-subject assignment after closing.

**Dependencies:** none (it does not depend on the other apps).
