"""Tests for the parser of the real study plans of EIC and TM (T0.6c).

Implements: D78 (the real plans may be in the repository), D79 (tracks, common subjects), D60
(contact hours = weekly hours x 15). The counts below come from reading
``docs/Planos_EIC_TM.md`` by hand: 44 EIC rows and 45 TM rows in the plan tables (the 5 optional
subjects and the 4 UCT tables are skipped), 41 + 45 = 86 subjects once the 3 subjects shared by
the two EIC tracks are counted once.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from apps.demo.real_plans import parse_plans, resolve_subjects, semester_position

D = Decimal
PLANS_FILE = Path(__file__).resolve().parents[3] / "docs" / "Planos_EIC_TM.md"


@pytest.fixture(scope="module")
def parsed():
    """The real file, parsed."""
    return parse_plans(PLANS_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def subjects(parsed):
    """The subjects of the real file after merging the common ones."""
    return resolve_subjects(parsed)


# --- the semester numbering --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (1, (1, 1)),
        (2, (1, 2)),
        (3, (2, 1)),
        (4, (2, 2)),
        (5, (3, 1)),
        (6, (3, 2)),
        (7, (4, 1)),
        (8, (4, 2)),
    ],
)
def test_semesters_one_to_eight_map_to_year_and_semester(number, expected):
    """Semester 7 of the course is the 1st semester of the 4th year."""
    assert semester_position(number) == expected


# --- the real file -----------------------------------------------------------------------------


def test_the_two_courses_are_found_with_their_codes_and_names(parsed):
    """EIC and TM, named without the 'Licenciatura em' prefix."""
    assert parsed.courses == {
        "EIC": "Engenharia Informática e de Computadores",
        "TM": "Tecnologias Multimédia",
    }


def test_the_four_tracks_start_in_the_fourth_year(parsed):
    """EIC has TIC and PSI; TM calls its tracks variants (Multimédia and Audiovisual)."""
    found = {(t.course, t.code, t.first_year) for t in parsed.tracks}
    assert found == {
        ("EIC", "TIC", 4),
        ("EIC", "PSI", 4),
        ("TM", "Multimédia", 4),
        ("TM", "Audiovisual", 4),
    }
    names = {t.code: t.name for t in parsed.tracks}
    assert names["TIC"] == "Tecnologias de Informação e Comunicação"
    assert names["Multimédia"] == "Multimédia"


def test_the_plan_tables_have_89_rows(parsed):
    """44 for EIC (32 + 6 + 6) and 45 for TM (35 + 5 + 5), before merging the common ones."""
    by_course = {c: sum(1 for r in parsed.rows if r.course == c) for c in parsed.courses}
    assert by_course == {"EIC": 44, "TM": 45}


def test_what_is_not_loaded_is_reported(parsed):
    """Four UCT tables (Q27) and five optional subjects (Q28)."""
    uct = [s for s in parsed.skipped if s.kind == "uct"]
    optional = [s for s in parsed.skipped if s.kind == "optional"]
    assert len(uct) == 4
    assert {s.description for s in optional} == {
        "Robótica e Automação",
        "Tecnologias Avançadas de Redes",
        "Processamento de Imagem e Biométrica",
        "Economia e Gestão",
        "Inglês Técnico",
    }


def test_86_subjects_remain_once_the_shared_ones_count_once(subjects):
    """EIC 41 (32 + 3 common + 3 TIC + 3 PSI) and TM 45."""
    counts = {c: sum(1 for s in subjects if s.course == c) for c in ("EIC", "TM")}
    assert counts == {"EIC": 41, "TM": 45}


def test_the_three_subjects_shared_by_tic_and_psi_are_common(subjects):
    """Identical in both tables, so they have no track (D79)."""
    common = {
        s.name for s in subjects if s.course == "EIC" and s.semester_number == 7 and s.track is None
    }
    assert common == {
        "Empreendedorismo de Base Tecnológica",
        "Design e Programação de Jogos",
        "Opção Condicionada",
    }


def test_the_own_subjects_of_each_eic_track(subjects):
    """Three each, all in the 7th semester."""
    own = {
        track: {s.name for s in subjects if s.course == "EIC" and s.track == track}
        for track in ("TIC", "PSI")
    }
    assert own["TIC"] == {
        "Sistemas e Infraestruturas de Computação",
        "Planeamento e Gestão de Redes",
        "Infraestruturas Seguras",
    }
    assert own["PSI"] == {
        "Integração de Sistemas de Informação",
        "Planeamento Estratégico de Sistemas de Informação",
        "Sistemas de Apoio à Decisão",
    }


def test_tm_has_no_common_subject_in_the_fourth_year(subjects):
    """The two TM variants share nothing in the 7th semester."""
    fourth = [s for s in subjects if s.course == "TM" and s.curricular_year == 4]
    assert len(fourth) == 10 and all(s.track is not None for s in fourth)


@pytest.mark.parametrize("track", ["TIC", "PSI", "Multimédia", "Audiovisual"])
def test_each_track_gets_30_ects_in_the_seventh_semester(subjects, track):
    """Common plus own subjects add up to the 30 ECTS of a semester."""
    total = sum(
        s.ects
        for s in subjects
        if s.semester_number == 7
        and (s.track == track or s.track is None)
        and s.course == ("TM" if track in ("Multimédia", "Audiovisual") else "EIC")
    )
    assert total == D("30")


def test_the_first_three_years_have_30_ects_per_semester(subjects):
    """Every semester of the first three years adds up to 30 ECTS in both courses."""
    for course in ("EIC", "TM"):
        for number in range(1, 7):
            total = sum(
                s.ects for s in subjects if s.course == course and s.semester_number == number
            )
            assert total == D("30"), (course, number)


def test_contact_hours_are_the_weekly_hours_times_fifteen_for_every_subject(subjects):
    """D60 holds for the whole real plan."""
    for s in subjects:
        assert sum(s.weekly.values()) * 15 == s.semester_hours, s.name


def test_the_practical_laboratory_column_is_loaded_as_practical(subjects):
    """Introdução à Programação has 3 T and 2 P/L, loaded as T 3 and P 2 (Q26)."""
    ip = next(s for s in subjects if s.course == "EIC" and s.name == "Introdução à Programação")
    assert ip.weekly == {"T": D("3"), "P": D("2")}
    assert (ip.curricular_year, ip.semester, ip.ects, ip.semester_hours) == (1, 1, D("6"), D("75"))


def test_a_subject_with_only_tp_keeps_that_class_type(subjects):
    """Introdução à Engenharia Informática has 3 TP and nothing else."""
    s = next(s for s in subjects if s.name == "Introdução à Engenharia Informática")
    assert s.weekly == {"TP": D("3")}


def test_subject_codes_are_unique_inside_a_course_and_stable(parsed):
    """The codes are placeholders but must be unique and the same on every run."""
    first = resolve_subjects(parsed)
    again = resolve_subjects(parsed)
    assert [s.code for s in first] == [s.code for s in again]
    for course in ("EIC", "TM"):
        codes = [s.code for s in first if s.course == course]
        assert len(codes) == len(set(codes))


# --- inconsistent files are refused, never guessed ---------------------------------------------

HEADER = (
    "| Unidade Curricular | Área | T | TP | P/L | Total | HC | HEA | Total | CTS | Obs. |\n"
    "|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|\n"
)


def table(*rows, total=None):
    """A plan table; ``total`` is the cells of the Total row (computed if omitted)."""
    body = "".join(f"| {r} |\n" for r in rows)
    return HEADER + body + (f"| {total} |\n" if total else "")


def doc(*blocks):
    """A one-course document."""
    return "## Licenciatura em Curso Teste (CT)\n\n" + "\n".join(blocks)


ROW_A = "Disciplina A | CETE | 3 | – | 2 | 5 | 75 | 75 | 150 | 6 | "


def test_contact_hours_that_are_not_weekly_times_fifteen_are_refused():
    """A row that breaks D60 stops the load with the subject named."""
    bad = "Disciplina A | CETE | 3 | – | 2 | 5 | 70 | 75 | 145 | 6 | "
    text = doc("### 1.º Ano — 1.º Semestre\n\n" + table(bad))
    with pytest.raises(ValueError, match="Disciplina A"):
        parse_plans(text)


def test_a_total_row_that_does_not_match_the_columns_is_refused():
    """The declared totals are checked against the rows."""
    wrong = "**Total** | | **3** | **0** | **2** | **6** | **75** | **75** | **150** | **6** | "
    text = doc("### 1.º Ano — 1.º Semestre\n\n" + table(ROW_A, total=wrong))
    with pytest.raises(ValueError, match="Total"):
        parse_plans(text)


def test_a_shared_subject_with_different_loads_in_two_tracks_is_refused():
    """The same name with different numbers in two tracks is not guessed to be common."""
    other = "Disciplina A | CETE | 2 | – | 3 | 5 | 75 | 75 | 150 | 6 | "
    text = doc(
        "### 4.º Ano — Percurso 1: Primeiro (P1)\n\n#### 7.º Semestre — P1\n\n" + table(ROW_A),
        "### 4.º Ano — Percurso 2: Segundo (P2)\n\n#### 7.º Semestre — P2\n\n" + table(other),
    )
    with pytest.raises(ValueError, match="Disciplina A"):
        resolve_subjects(parse_plans(text))


def test_a_subject_in_some_but_not_all_of_three_tracks_is_refused():
    """Partial sharing is not modelled (D79), so the loader stops instead of guessing."""
    blocks = [
        f"### 4.º Ano — Percurso {i}: Nome {i} (P{i})\n\n#### 7.º Semestre — P{i}\n\n"
        + table(ROW_A if i < 3 else "Disciplina B | CETE | 3 | – | 2 | 5 | 75 | 75 | 150 | 6 | ")
        for i in (1, 2, 3)
    ]
    with pytest.raises(ValueError, match="Disciplina A"):
        resolve_subjects(parse_plans(doc(*blocks)))


def test_a_subject_in_every_track_with_the_same_numbers_becomes_common():
    """Two tracks with identical rows give one common subject."""
    blocks = [
        f"### 4.º Ano — Percurso {i}: Nome {i} (P{i})\n\n#### 7.º Semestre — P{i}\n\n"
        + table(ROW_A)
        for i in (1, 2)
    ]
    (subject,) = resolve_subjects(parse_plans(doc(*blocks)))
    assert (subject.name, subject.track) == ("Disciplina A", None)
