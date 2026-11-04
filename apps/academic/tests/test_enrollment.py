"""Tests for the enrollment model and its services (T1.1).

Implements: docs/especificacao/02_perfis_e_dados.md – the Serviços Académicos enter the number of
students; D49 and D79 (a turma only exists in some years), D66 (numbers, no names), D76, D81.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    Course,
    Enrollment,
    Faculty,
    StudyPlan,
    Track,
)
from apps.academic.services import class_group_size, class_group_sizes
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
def plan(course, years):
    """The plan that starts in 2023."""
    return StudyPlan.objects.create(course=course, academic_year=years[2023])


@pytest.fixture
def group(course, plan, years):
    """A turma that enters in 2023, in a plan without tracks."""
    return ClassGroup.objects.create(course=course, intake_year=years[2023], study_plan=plan)


def enrol(group, year, kind=Enrollment.Kind.ACTUAL, students=30, **extra):
    """Create an enrollment."""
    return Enrollment.objects.create(
        class_group=group, academic_year=year, kind=kind, students=students, **extra
    )


def test_a_turma_has_an_estimated_and_a_real_number_in_the_same_year(group, years):
    """Both kinds can coexist for one turma and year (D76)."""
    enrol(group, years[2023], Enrollment.Kind.ESTIMATED, 30)
    enrol(group, years[2023], Enrollment.Kind.ACTUAL, 28)
    assert Enrollment.objects.count() == 2


def test_a_second_number_of_the_same_kind_in_a_year_is_refused(group, years):
    """One estimate and one real number per turma and year, enforced by the database."""
    enrol(group, years[2023])
    with pytest.raises(IntegrityError), transaction.atomic():
        enrol(group, years[2023], students=31)


def test_the_same_turma_has_a_number_in_each_year(group, years):
    """The turma moves up a year every year, so each year has its own number."""
    enrol(group, years[2023])
    enrol(group, years[2024], students=26)
    assert Enrollment.objects.count() == 2


def test_zero_students_is_accepted_but_not_a_negative_number(group, years):
    """A turma may have no students left; -1 is meaningless."""
    enrol(group, years[2023], students=0).full_clean()
    with pytest.raises((IntegrityError, ValidationError)), transaction.atomic():
        bad = Enrollment(class_group=group, academic_year=years[2024], students=-1)
        bad.full_clean()
        bad.save()


def test_the_source_is_manual_unless_the_import_says_otherwise(group, years):
    """Typed by the Serviços Académicos by default; the SII import marks its rows."""
    assert enrol(group, years[2023]).source == Enrollment.Source.MANUAL
    imported = enrol(group, years[2024], source=Enrollment.Source.SII)
    assert imported.source == Enrollment.Source.SII


def test_no_numbers_for_a_year_before_the_turma_enters(group, years):
    """The turma enters in 2023: there is nothing to count in 2022."""
    with pytest.raises(ValidationError) as error:
        enrol(group, years[2022])
    assert "academic_year" in error.value.message_dict


def test_no_numbers_after_the_last_academic_year_of_the_turma(course, plan, years):
    """A turma that ended in 2024 has no number in 2025."""
    ended = ClassGroup.objects.create(
        course=course,
        intake_year=years[2023],
        study_plan=plan,
        label="B",
        last_academic_year=years[2024],
    )
    enrol(ended, years[2024])
    with pytest.raises(ValidationError):
        enrol(ended, years[2025])


def test_the_model_clean_reports_the_year_error_for_forms(group, years):
    """``full_clean`` shows the error on the field."""
    row = Enrollment(class_group=group, academic_year=years[2022], students=3)
    with pytest.raises(ValidationError) as error:
        row.full_clean()
    assert "academic_year" in error.value.message_dict


def test_track_turmas_have_numbers_only_from_the_year_of_their_track(course, plan, years):
    """TIC exists from the 4th year: 2026 for an intake in 2023 (D79)."""
    tic = Track.objects.create(study_plan=plan, code="TIC", name="TIC", first_curricular_year=4)
    track_turma = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, track=tic
    )
    with pytest.raises(ValidationError):
        enrol(track_turma, years[2025])  # 3rd year: the track turma does not exist yet
    enrol(track_turma, years[2026])


def test_the_cohort_turma_has_no_number_once_the_tracks_start(course, plan, years):
    """In a plan with tracks the turma without track stops at the 3rd year (D79)."""
    Track.objects.create(study_plan=plan, code="TIC", name="TIC", first_curricular_year=4)
    cohort = ClassGroup.objects.create(course=course, intake_year=years[2023], study_plan=plan)
    enrol(cohort, years[2025])
    with pytest.raises(ValidationError):
        enrol(cohort, years[2026])


def test_a_turma_or_a_year_with_numbers_cannot_be_deleted(group, years):
    """The numbers protect their turma and their year."""
    enrol(group, years[2023])
    with pytest.raises(ProtectedError):
        group.delete()
    with pytest.raises(ProtectedError):
        years[2023].delete()


def test_changes_are_audited_with_the_old_and_new_numbers(group, years):
    """Creating and updating go through the audit log (D40)."""
    actor = None
    row = Enrollment(class_group=group, academic_year=years[2023], students=30)
    audited_save(row, actor, "")
    row.students = 28
    audited_save(row, actor, "Número real do SII")
    entry = AuditEntry.objects.filter(entity="academic.enrollment").latest("pk")
    assert (entry.old_value["students"], entry.new_value["students"]) == (30, 28)


# --- the services ------------------------------------------------------------------------------


def test_the_size_of_a_turma_is_the_estimate_until_the_real_number_arrives(group, years):
    """Only an estimate: provisional. With the real number: the real one (D76)."""
    assert class_group_size(group, years[2023]) is None
    enrol(group, years[2023], Enrollment.Kind.ESTIMATED, 30)
    size = class_group_size(group, years[2023])
    assert (size.students, size.provisional) == (30, True)
    enrol(group, years[2023], Enrollment.Kind.ACTUAL, 27)
    size = class_group_size(group, years[2023])
    assert (size.students, size.provisional) == (27, False)


def test_the_sizes_of_a_year_are_given_for_every_turma_with_a_number(course, plan, group, years):
    """One entry per turma that has any number that year; none for the others."""
    other = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, label="B"
    )
    third = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, label="C"
    )
    enrol(group, years[2024], Enrollment.Kind.ESTIMATED, 30)
    enrol(other, years[2024], Enrollment.Kind.ACTUAL, 25)
    enrol(other, years[2024], Enrollment.Kind.ESTIMATED, 28)
    sizes = class_group_sizes(years[2024])
    assert set(sizes) == {group.pk, other.pk} and third.pk not in sizes
    assert (sizes[group.pk].students, sizes[group.pk].provisional) == (30, True)
    assert (sizes[other.pk].students, sizes[other.pk].provisional) == (25, False)


def test_the_sizes_of_one_year_do_not_include_another_year(group, years):
    """The service is per academic year."""
    enrol(group, years[2023], students=31)
    enrol(group, years[2024], students=26)
    assert class_group_sizes(years[2023])[group.pk].students == 31
    assert class_group_sizes(years[2024])[group.pk].students == 26
