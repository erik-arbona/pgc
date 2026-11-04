"""Tests for the loader of the real study plans and its command (T0.6c).

Implements: D78 (real plans in the repository, fictitious people only), D79 (tracks), D60.
The loader creates courses, plans, tracks and subjects; it never deletes and is safe to run
twice. The Faculty and the coordination of each subject are unknown, so they are given or
replaced by clearly marked placeholders.
"""

from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
    Track,
)
from apps.academic.services import subjects_for

pytestmark = pytest.mark.django_db


def run(*args, **kwargs):
    """Run the command in development mode with placeholders unless told otherwise."""
    if not args and not any(k in kwargs for k in ("faculty", "coordination")):
        args = ("--placeholders",)
    call_command("load_real_plans", *args, "--force", **kwargs)


@pytest.fixture
def loaded():
    """The real plans loaded with placeholders."""
    run()


def test_the_load_creates_the_courses_plans_tracks_and_subjects(loaded):
    """2 courses, 2 plans, 4 tracks and 86 subjects."""
    assert Course.objects.count() == 2
    assert StudyPlan.objects.count() == 2
    assert Track.objects.count() == 4
    assert Subject.objects.count() == 86


def test_the_plans_start_in_the_assumed_years(loaded):
    """EIC 2023 and TM 2024, the defaults (the start year of TM is an assumption)."""
    years = {p.course.name: p.academic_year.start_year for p in StudyPlan.objects.all()}
    assert years == {
        "Engenharia Informática e de Computadores": 2023,
        "Tecnologias Multimédia": 2024,
    }


def test_the_start_years_can_be_changed():
    """The options override the defaults."""
    run("--placeholders", "--eic-year", "2022", "--tm-year", "2025")
    assert set(AcademicYear.objects.values_list("start_year", flat=True)) == {2022, 2025}


def test_the_placeholders_are_clearly_marked(loaded):
    """The Faculty and the coordination say they must be confirmed."""
    faculty = Faculty.objects.get()
    assert faculty.code == "PORCONF" and "confirmar" in faculty.name
    coordination = Coordination.objects.get()
    assert "atribuir" in coordination.name
    assert set(Subject.objects.values_list("coordination", flat=True)) == {coordination.pk}


def test_running_twice_creates_nothing_new(loaded):
    """Idempotent: the second run adds no record."""
    before = (Course.objects.count(), Track.objects.count(), Subject.objects.count())
    run()
    assert (Course.objects.count(), Track.objects.count(), Subject.objects.count()) == before


def test_a_subject_whose_code_was_edited_is_not_duplicated(loaded):
    """Subjects are found by plan, name, year, semester and track, not by the generated code."""
    subject = Subject.objects.filter(name="Introdução à Programação").first()
    subject.code = "IP-OFICIAL"
    subject.save()
    run()
    assert Subject.objects.count() == 86
    subject.refresh_from_db()
    assert subject.code == "IP-OFICIAL"


def test_the_weekly_hours_are_stored_per_class_type(loaded):
    """3 T and 2 P/L become T 3 and P 2, with 75 contact hours (D60, Q26)."""
    ip = Subject.objects.get(
        name="Introdução à Programação", study_plan__course__name__startswith="Eng"
    )
    rows = ip.class_loads.select_related("class_type")
    loads = {row.class_type.code: row.weekly_hours for row in rows}
    assert loads == {"T": Decimal("3.00"), "P": Decimal("2.00")}
    assert (ip.semester_hours, ip.ects, ip.curricular_year, ip.semester) == (
        Decimal("75.00"),
        Decimal("6.00"),
        1,
        1,
    )


def test_common_subjects_have_no_track_and_own_subjects_have_theirs(loaded):
    """Empreendedorismo is common to TIC and PSI; Infraestruturas Seguras is TIC only."""
    common = Subject.objects.get(
        name="Empreendedorismo de Base Tecnológica",
        track__isnull=True,
        study_plan__course__name__startswith="Eng",
    )
    assert common.curricular_year == 4
    own = Subject.objects.get(name="Infraestruturas Seguras")
    assert own.track.code == "TIC"


def test_every_track_starts_in_the_fourth_year(loaded):
    """The first curricular year of the four tracks comes from the plan."""
    assert set(Track.objects.values_list("first_curricular_year", flat=True)) == {4}


def test_the_sii_references_are_left_empty(loaded):
    """Nothing is invented for the SII (D66, D77)."""
    assert not Subject.objects.exclude(sii_ref="").exists()
    assert not Course.objects.exclude(sii_ref="").exists()


def test_the_example_turmas_are_a_cohort_and_one_per_track():
    """With --turmas each course gets a cohort turma and one turma per track."""
    run("--placeholders", "--turmas")
    assert ClassGroup.objects.count() == 6
    assert ClassGroup.objects.filter(track__isnull=True).count() == 2
    tic = ClassGroup.objects.get(track__code="TIC")
    cohort = ClassGroup.objects.get(course=tic.course, track__isnull=True)
    assert tic.intake_year == cohort.intake_year and tic.study_plan == cohort.study_plan


def test_a_track_turma_sees_the_common_subjects_and_its_own():
    """The TIC turma sees 32 subjects of years 1 to 3, 3 common and 3 own; the cohort 35."""
    run("--placeholders", "--turmas")
    tic = ClassGroup.objects.get(track__code="TIC")
    psi = ClassGroup.objects.get(track__code="PSI")
    cohort = ClassGroup.objects.get(course=tic.course, track__isnull=True)
    assert subjects_for(tic).count() == 38
    assert subjects_for(psi).count() == 38
    assert subjects_for(cohort).count() == 35
    assert not set(subjects_for(tic)) & {s for s in subjects_for(psi) if s.track_id}


def test_running_with_turmas_twice_creates_no_extra_turma():
    """The turmas are found by course, intake and track."""
    run("--placeholders", "--turmas")
    run("--placeholders", "--turmas")
    assert ClassGroup.objects.count() == 6


def test_given_faculty_and_coordination_are_used_instead_of_the_placeholders():
    """With --faculty and --coordination nothing is invented."""
    faculty = Faculty.objects.create(name="Faculdade de Teste", code="FT")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação de Teste")
    run("--faculty", "FT", "--coordination", "Coordenação de Teste")
    assert Faculty.objects.count() == 1
    assert set(Subject.objects.values_list("coordination", flat=True)) == {coordination.pk}
    assert set(Course.objects.values_list("faculty", flat=True)) == {faculty.pk}


def test_without_a_faculty_or_placeholders_the_command_refuses():
    """It cannot know the Faculty, so it must be told or allowed to use placeholders."""
    with pytest.raises(CommandError):
        call_command("load_real_plans", "--force")
    assert not Course.objects.exists()


def test_an_unknown_faculty_or_coordination_is_refused():
    """The names given must exist; nothing is created for them."""
    with pytest.raises(CommandError):
        run("--faculty", "XX", "--coordination", "Nenhuma")
    assert not Course.objects.exists()


def test_the_command_refuses_to_run_with_debug_off_without_force(settings):
    """Like the demo loader: development only unless forced."""
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("load_real_plans", "--placeholders")
    assert not Course.objects.exists()


def test_the_command_reports_what_it_skipped(capsys):
    """The output lists the UCT tables and the optional subjects that were not loaded."""
    run()
    out = capsys.readouterr().out
    assert "UCT" in out and "Robótica e Automação" in out and "86" in out
