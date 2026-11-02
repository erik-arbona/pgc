"""Tests for the enrollment model and its services (T1.1).

Implements: D66 (numbers, no names), D76 (estimated, then real), D81 – the enrollment is the
number of students of a subject in an academic year, estimated first and real later; D49 and
D79 (which turmas exist in which years, and which subjects they see).
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    Coordination,
    Course,
    Enrollment,
    Faculty,
    StudyPlan,
    Subject,
    Track,
)
from apps.academic.services import subject_enrollment, subject_enrollments
from apps.core.audit import audited_save
from apps.core.models import AuditEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def years():
    """Academic years 2022 to 2028, by start year."""
    return {y: AcademicYear.objects.create(start_year=y) for y in range(2022, 2029)}


@pytest.fixture
def course():
    """A bachelor course."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    return Course.objects.create(faculty=faculty, name="EIC", level="bachelor")


@pytest.fixture
def coordination(course):
    """A coordination of the course's Faculty."""
    return Coordination.objects.create(faculty=course.faculty, name="Coordenação A")


@pytest.fixture
def plan(course, years):
    """The plan that starts in 2023."""
    return StudyPlan.objects.create(course=course, academic_year=years[2023])


def make_subject(plan, coordination, code="S1", curricular_year=1, **extra):
    """Create a subject of the plan."""
    data = dict(
        study_plan=plan,
        code=code,
        name=f"Disciplina {code}",
        ects=Decimal("6"),
        curricular_year=curricular_year,
        semester=1,
        coordination=coordination,
        semester_hours=Decimal("60"),
    )
    data.update(extra)
    return Subject.objects.create(**data)


def make_group(course, plan, year, label="", **extra):
    """Create a turma that enters in ``year``."""
    return ClassGroup.objects.create(
        course=course, intake_year=year, study_plan=plan, label=label, **extra
    )


@pytest.fixture
def first_year_subject(plan, coordination):
    """A subject of the 1st curricular year."""
    return make_subject(plan, coordination)


@pytest.fixture
def cohort(course, plan, years):
    """The turma that enters in 2023 (1st year in 2023, 2nd in 2024...)."""
    return make_group(course, plan, years[2023])


def enrol(subject, year, kind=Enrollment.Kind.ACTUAL, students=30, **extra):
    """Create an enrollment."""
    return Enrollment.objects.create(
        subject=subject, academic_year=year, kind=kind, students=students, **extra
    )


# --- the numbers -------------------------------------------------------------------------------


def test_a_subject_has_an_estimated_and_a_real_number_in_the_same_year(
    first_year_subject, cohort, years
):
    """Both kinds can coexist for one subject and year (D76)."""
    enrol(first_year_subject, years[2023], Enrollment.Kind.ESTIMATED, 30)
    enrol(first_year_subject, years[2023], Enrollment.Kind.ACTUAL, 28)
    assert Enrollment.objects.count() == 2


def test_a_second_number_of_the_same_kind_in_a_year_is_refused(first_year_subject, cohort, years):
    """One estimate and one real number per subject and year, enforced by the database."""
    enrol(first_year_subject, years[2023])
    with pytest.raises(IntegrityError), transaction.atomic():
        enrol(first_year_subject, years[2023], students=31)


def test_zero_students_is_accepted_but_not_a_negative_number(first_year_subject, cohort, years):
    """A subject may have no students; -1 is meaningless."""
    enrol(first_year_subject, years[2023], students=0).full_clean()
    with pytest.raises((IntegrityError, ValidationError)), transaction.atomic():
        bad = Enrollment(subject=first_year_subject, academic_year=years[2023], students=-1)
        bad.full_clean()
        bad.save()


def test_the_source_is_manual_unless_the_import_says_otherwise(first_year_subject, cohort, years):
    """Typed by the Serviços Académicos by default; the SII import marks its rows."""
    assert enrol(first_year_subject, years[2023]).source == Enrollment.Source.MANUAL
    imported = enrol(
        first_year_subject, years[2023], Enrollment.Kind.ESTIMATED, source=Enrollment.Source.SII
    )
    assert imported.source == Enrollment.Source.SII


# --- the subject must be taught in the year ----------------------------------------------------


def test_no_numbers_for_a_subject_nobody_attends_that_year(first_year_subject, cohort, years):
    """The turma that enters in 2023 is in its 2nd year in 2024, so nobody attends the
    1st-year subject in 2024, nor in 2022 before it exists."""
    with pytest.raises(ValidationError) as error:
        enrol(first_year_subject, years[2024])
    assert "academic_year" in error.value.message_dict
    with pytest.raises(ValidationError):
        enrol(first_year_subject, years[2022])


def test_a_new_turma_entering_makes_the_year_valid_again(
    first_year_subject, cohort, course, plan, years
):
    """A turma that enters in 2024 attends the 1st-year subject in 2024."""
    make_group(course, plan, years[2024])
    enrol(first_year_subject, years[2024])


def test_a_subject_with_no_turma_at_all_has_no_numbers(first_year_subject, years):
    """Without any turma following the plan the subject is not taught."""
    with pytest.raises(ValidationError):
        enrol(first_year_subject, years[2023])


def test_a_turma_that_follows_another_plan_does_not_count(first_year_subject, course, years):
    """Only turmas of the subject's own plan attend its subjects (D48)."""
    other = StudyPlan.objects.create(course=course, academic_year=years[2025])
    make_group(course, other, years[2025])
    with pytest.raises(ValidationError):
        enrol(first_year_subject, years[2025])


def test_no_numbers_after_the_last_academic_year_of_the_turma(plan, coordination, course, years):
    """A turma that ended in 2023 no longer attends its 2nd-year subjects in 2024."""
    second_year = make_subject(plan, coordination, "S2", curricular_year=2)
    make_group(course, plan, years[2023], last_academic_year=years[2023])
    with pytest.raises(ValidationError):
        enrol(second_year, years[2024])


def test_the_model_clean_reports_the_year_error_for_forms(first_year_subject, cohort, years):
    """``full_clean`` shows the error on the field."""
    row = Enrollment(subject=first_year_subject, academic_year=years[2024], students=3)
    with pytest.raises(ValidationError) as error:
        row.full_clean()
    assert "academic_year" in error.value.message_dict


def test_track_subjects_have_numbers_only_from_the_year_of_their_track(
    course, plan, coordination, years
):
    """A TIC subject of the 4th year is attended in 2026 by the TIC turma that entered in 2023
    (D79); not in 2025, when that turma does not exist yet."""
    tic = Track.objects.create(study_plan=plan, code="TIC", name="TIC", first_curricular_year=4)
    subject = make_subject(plan, coordination, "T1", curricular_year=4, track=tic)
    make_group(course, plan, years[2023], track=tic)
    with pytest.raises(ValidationError):
        enrol(subject, years[2025])
    enrol(subject, years[2026])


def test_a_track_subject_is_not_attended_by_the_turma_of_another_track(
    course, plan, coordination, years
):
    """Only the PSI turma exists: nobody attends a TIC subject."""
    tic = Track.objects.create(study_plan=plan, code="TIC", name="TIC", first_curricular_year=4)
    psi = Track.objects.create(study_plan=plan, code="PSI", name="PSI", first_curricular_year=4)
    subject = make_subject(plan, coordination, "T1", curricular_year=4, track=tic)
    make_group(course, plan, years[2023], track=psi)
    with pytest.raises(ValidationError):
        enrol(subject, years[2026])


def test_a_common_subject_of_the_fourth_year_is_attended_by_the_track_turmas(
    course, plan, coordination, years
):
    """A common subject (no track) is seen by the track turmas (D79)."""
    tic = Track.objects.create(study_plan=plan, code="TIC", name="TIC", first_curricular_year=4)
    common = make_subject(plan, coordination, "C1", curricular_year=4)
    make_group(course, plan, years[2023], track=tic)
    enrol(common, years[2026])


def test_the_cohort_turma_does_not_attend_the_fourth_year_when_tracks_exist(
    course, plan, coordination, years
):
    """Only the cohort turma exists and the plan has tracks: it stops at the 3rd year, so a
    common 4th-year subject has nobody in 2026 (D79)."""
    Track.objects.create(study_plan=plan, code="TIC", name="TIC", first_curricular_year=4)
    common = make_subject(plan, coordination, "C1", curricular_year=4)
    make_group(course, plan, years[2023])
    with pytest.raises(ValidationError):
        enrol(common, years[2026])


# --- protection and audit ----------------------------------------------------------------------


def test_a_subject_or_a_year_with_numbers_cannot_be_deleted(first_year_subject, cohort, years):
    """The numbers protect their subject and their year."""
    enrol(first_year_subject, years[2023])
    with pytest.raises(ProtectedError):
        first_year_subject.delete()
    with pytest.raises(ProtectedError):
        years[2023].delete()


def test_changes_are_audited_with_the_old_and_new_numbers(first_year_subject, cohort, years):
    """Creating and updating go through the audit log (D40)."""
    row = Enrollment(subject=first_year_subject, academic_year=years[2023], students=30)
    audited_save(row, None, "")
    row.students = 28
    audited_save(row, None, "Número real do SII")
    entry = AuditEntry.objects.filter(entity="academic.enrollment").latest("pk")
    assert (entry.old_value["students"], entry.new_value["students"]) == (30, 28)


# --- the services ------------------------------------------------------------------------------


def test_the_number_of_a_subject_is_the_estimate_until_the_real_number_arrives(
    first_year_subject, cohort, years
):
    """Only an estimate: provisional. With the real number: the real one (D76)."""
    assert subject_enrollment(first_year_subject, years[2023]) is None
    enrol(first_year_subject, years[2023], Enrollment.Kind.ESTIMATED, 30)
    number = subject_enrollment(first_year_subject, years[2023])
    assert (number.students, number.provisional) == (30, True)
    enrol(first_year_subject, years[2023], Enrollment.Kind.ACTUAL, 27)
    number = subject_enrollment(first_year_subject, years[2023])
    assert (number.students, number.provisional) == (27, False)


def test_the_numbers_of_a_year_cover_every_subject_that_has_one(plan, coordination, cohort, years):
    """One entry per subject that has any number that year; none for the others."""
    first = make_subject(plan, coordination, "A1")
    second = make_subject(plan, coordination, "A2")
    third = make_subject(plan, coordination, "A3")
    enrol(first, years[2023], Enrollment.Kind.ESTIMATED, 30)
    enrol(second, years[2023], Enrollment.Kind.ACTUAL, 25)
    enrol(second, years[2023], Enrollment.Kind.ESTIMATED, 28)
    numbers = subject_enrollments(years[2023])
    assert set(numbers) == {first.pk, second.pk} and third.pk not in numbers
    assert (numbers[first.pk].students, numbers[first.pk].provisional) == (30, True)
    assert (numbers[second.pk].students, numbers[second.pk].provisional) == (25, False)


def test_the_numbers_of_one_year_do_not_include_another_year(
    first_year_subject, cohort, course, plan, years
):
    """The service is per academic year."""
    make_group(course, plan, years[2024])
    enrol(first_year_subject, years[2023], students=31)
    enrol(first_year_subject, years[2024], students=26)
    assert subject_enrollments(years[2023])[first_year_subject.pk].students == 31
    assert subject_enrollments(years[2024])[first_year_subject.pk].students == 26
