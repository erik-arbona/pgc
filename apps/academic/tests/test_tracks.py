"""Tests for the tracks (percursos) of a course plan (T0.6a).

Implements: D75 – the 4th year of some courses has tracks, each one a separate turma of the same
course; common subjects have no track and the two turmas can be merged in them (D23); D79.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.academic.class_groups import curricular_year_in, subject_applies
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
from apps.academic.services import create_class_group, subjects_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def faculty():
    """A Faculty."""
    return Faculty.objects.create(name="Faculdade A", code="FA")


@pytest.fixture
def coordination(faculty):
    """A coordination of the Faculty."""
    return Coordination.objects.create(faculty=faculty, name="Coordenação A")


@pytest.fixture
def course(faculty):
    """A bachelor course."""
    return Course.objects.create(faculty=faculty, name="EIC", level="bachelor")


@pytest.fixture
def years():
    """Academic years 2023 to 2027, by start year."""
    return {y: AcademicYear.objects.create(start_year=y) for y in range(2023, 2028)}


@pytest.fixture
def plan(course, years):
    """The plan that starts in 2023."""
    return StudyPlan.objects.create(course=course, academic_year=years[2023])


@pytest.fixture
def tic(plan):
    """Track TIC, from the 4th year."""
    return Track.objects.create(
        study_plan=plan, code="TIC", name="Tecnologias", first_curricular_year=4
    )


@pytest.fixture
def psi(plan):
    """Track PSI, from the 4th year."""
    return Track.objects.create(
        study_plan=plan, code="PSI", name="Programação", first_curricular_year=4
    )


@pytest.fixture
def other_plan(course, years):
    """A newer plan of the same course."""
    return StudyPlan.objects.create(course=course, academic_year=years[2025])


def make_subject(plan, coordination, code="S1", **extra):
    """Create a valid subject (4 weekly hours would be added by the services, not needed here)."""
    data = dict(
        study_plan=plan,
        code=code,
        name=f"Disciplina {code}",
        ects=Decimal("6"),
        curricular_year=4,
        semester=1,
        coordination=coordination,
        semester_hours=Decimal("75"),
    )
    data.update(extra)
    return Subject.objects.create(**data)


# --- the track itself --------------------------------------------------------------------------


def test_a_track_code_and_name_are_unique_inside_a_plan(plan, tic):
    """Two tracks of one plan cannot share a code or a name."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Track.objects.create(study_plan=plan, code="TIC", name="Outro", first_curricular_year=4)
    with pytest.raises(IntegrityError), transaction.atomic():
        Track.objects.create(study_plan=plan, code="X", name="Tecnologias", first_curricular_year=4)


def test_the_same_track_code_may_exist_in_another_plan(other_plan, tic):
    """Each plan version has its own tracks (D79)."""
    Track.objects.create(
        study_plan=other_plan, code="TIC", name="Tecnologias", first_curricular_year=4
    )
    assert Track.objects.filter(code="TIC").count() == 2


def test_a_track_starts_in_year_one_or_later(plan):
    """The first curricular year of a track is at least 1."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Track.objects.create(study_plan=plan, code="Z", name="Z", first_curricular_year=0)


def test_a_track_in_use_cannot_be_deleted(plan, tic, coordination):
    """Subjects and turmas protect their track."""
    make_subject(plan, coordination, track=tic)
    with pytest.raises(ProtectedError):
        tic.delete()


def test_a_sii_reference_identifies_one_track_per_plan(plan, tic, psi):
    """Like courses and subjects (D68): non-empty references are unique inside the plan."""
    tic.sii_ref = "TIC-1"
    tic.save()
    psi.sii_ref = "TIC-1"
    with pytest.raises(IntegrityError), transaction.atomic():
        psi.save()


# --- subjects ----------------------------------------------------------------------------------


def test_a_subject_without_a_track_is_common(plan, coordination):
    """No track means common to every track (D79)."""
    assert make_subject(plan, coordination).track is None


def test_a_subject_may_belong_to_a_track_of_its_plan(plan, coordination, tic):
    """A track subject of the 4th year is accepted."""
    assert make_subject(plan, coordination, track=tic).track == tic


def test_a_subject_cannot_have_a_track_of_another_plan(plan, other_plan, coordination, tic):
    """The track must belong to the plan of the subject."""
    with pytest.raises(ValidationError) as error:
        make_subject(other_plan, coordination, track=tic)
    assert "track" in error.value.message_dict


def test_a_subject_cannot_be_in_a_track_before_the_track_starts(plan, coordination, tic):
    """A 3rd-year subject cannot belong to a track that starts in the 4th year."""
    with pytest.raises(ValidationError) as error:
        make_subject(plan, coordination, track=tic, curricular_year=3)
    assert "track" in error.value.message_dict


def test_the_model_clean_reports_the_same_track_errors_for_forms(
    plan, other_plan, coordination, tic
):
    """``full_clean`` shows the error on the field, as the screens need."""
    subject = Subject(
        study_plan=other_plan,
        code="S9",
        name="X",
        ects=Decimal("6"),
        curricular_year=4,
        semester=1,
        coordination=coordination,
        semester_hours=Decimal("75"),
        track=tic,
    )
    with pytest.raises(ValidationError) as error:
        subject.full_clean()
    assert "track" in error.value.message_dict


# --- turmas ------------------------------------------------------------------------------------


def test_a_turma_may_have_a_track_of_its_plan(course, plan, tic, years):
    """A turma of a track is a turma of the same course and plan, with a track."""
    group = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, track=tic
    )
    assert (group.course, group.study_plan, group.track) == (course, plan, tic)


def test_a_turma_cannot_have_a_track_of_another_plan(course, plan, other_plan, tic, years):
    """The track must belong to the plan the turma follows."""
    with pytest.raises(ValidationError) as error:
        ClassGroup.objects.create(
            course=course, intake_year=years[2025], study_plan=other_plan, track=tic
        )
    assert "track" in error.value.message_dict


def test_the_track_of_a_turma_does_not_change(course, plan, tic, psi, years):
    """Like the plan (D54): it is fixed when the turma is created."""
    group = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, track=tic
    )
    group.track = psi
    with pytest.raises(ValidationError) as error:
        group.save()
    assert "track" in error.value.message_dict
    group.refresh_from_db()
    group.track = None
    with pytest.raises(ValidationError):
        group.save()


def test_two_turmas_of_the_same_intake_may_differ_in_the_track(course, plan, tic, psi, years):
    """TIC and PSI turmas of one intake, both with an empty label, can coexist."""
    for track in (tic, psi):
        ClassGroup.objects.create(
            course=course, intake_year=years[2023], study_plan=plan, track=track
        )
    assert ClassGroup.objects.count() == 2


def test_two_turmas_with_the_same_track_intake_and_label_are_refused(course, plan, tic, years):
    """The label still tells turmas apart inside a track."""
    ClassGroup.objects.create(course=course, intake_year=years[2023], study_plan=plan, track=tic)
    with pytest.raises(IntegrityError), transaction.atomic():
        ClassGroup.objects.create(
            course=course, intake_year=years[2023], study_plan=plan, track=tic
        )


def test_two_turmas_without_a_track_with_the_same_label_are_still_refused(course, plan, years):
    """The old rule holds: with no track, an empty label is the default turma and is unique."""
    ClassGroup.objects.create(course=course, intake_year=years[2023], study_plan=plan)
    with pytest.raises(IntegrityError), transaction.atomic():
        ClassGroup.objects.create(course=course, intake_year=years[2023], study_plan=plan)


def test_the_name_of_a_turma_shows_its_track(course, plan, tic, years):
    """The track code appears after the intake year."""
    group = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, track=tic
    )
    assert str(group).endswith("TIC")


# --- curricular year of a turma with tracks ---------------------------------------------------


@pytest.mark.parametrize(
    ("academic_year", "first_year", "final_year", "expected"),
    [
        (2023, 1, None, 1),  # unchanged for plans without tracks
        (2026, 1, None, 4),
        (2025, 4, None, None),  # a track turma is not active before its first year
        (2026, 4, None, 4),  # exactly at the first year
        (2027, 4, None, 5),
        (2025, 1, 3, 3),  # the cohort turma is active up to the year before the tracks
        (2026, 1, 3, None),  # and not from the first year of the tracks
        (2022, 1, 3, None),  # not before the intake
    ],
)
def test_curricular_year_respects_the_first_and_final_year(
    academic_year, first_year, final_year, expected
):
    """The bounds cut the active years of a turma; with no bounds nothing changes (D49)."""
    result = curricular_year_in(
        2023, academic_year, None, first_year=first_year, final_year=final_year
    )
    assert result == expected


def test_a_track_turma_is_active_from_the_4th_year_and_the_cohort_turma_stops_there(
    course, plan, tic, psi, years
):
    """With tracks in the plan, the turma without track covers years 1 to 3 and the track
    turmas year 4 (assumption A1 of D79)."""
    cohort = ClassGroup.objects.create(course=course, intake_year=years[2023], study_plan=plan)
    track_turma = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, track=tic
    )
    assert [cohort.curricular_year_in(y) for y in (2023, 2025, 2026)] == [1, 3, None]
    assert [track_turma.curricular_year_in(y) for y in (2023, 2025, 2026)] == [None, None, 4]


def test_a_plan_without_tracks_behaves_as_before(course, plan, years):
    """A turma of a plan with no tracks is active in all its years."""
    group = ClassGroup.objects.create(course=course, intake_year=years[2023], study_plan=plan)
    assert [group.curricular_year_in(y) for y in (2023, 2026, 2027)] == [1, 4, 5]


# --- which subjects a turma sees --------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject_track", "group_track", "expected"),
    [
        (None, None, True),  # common subject, turma without track
        (None, 7, True),  # common subject, track turma
        (7, 7, True),  # own subject
        (7, 8, False),  # subject of another track
        (7, None, False),  # a track subject is not for the cohort turma
    ],
)
def test_subject_applies_truth_table(subject_track, group_track, expected):
    """A turma sees the common subjects and those of its own track only."""
    assert subject_applies(subject_track, group_track) is expected


def test_a_turma_sees_the_common_subjects_and_those_of_its_track(
    course, plan, tic, psi, coordination, years
):
    """Common subjects plus the track's own, not the other track's."""
    common = make_subject(plan, coordination, "C1")
    own_tic = make_subject(plan, coordination, "T1", track=tic)
    own_psi = make_subject(plan, coordination, "P1", track=psi)
    before = make_subject(plan, coordination, "B1", curricular_year=2)
    group_tic = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, track=tic
    )
    cohort = ClassGroup.objects.create(course=course, intake_year=years[2023], study_plan=plan)
    assert set(subjects_for(group_tic)) == {common, own_tic, before}
    assert set(subjects_for(cohort)) == {common, before}
    assert own_psi not in subjects_for(group_tic)


# --- creating a turma with a track ------------------------------------------------------------


def test_create_class_group_accepts_a_track_of_the_plan_in_force(course, plan, tic, years):
    """The service picks the plan in force (D48) and checks the track against it."""
    group = create_class_group(course, years[2023], track=tic, actor=None)
    assert (group.study_plan, group.track) == (plan, tic)


def test_create_class_group_refuses_a_track_of_another_plan(course, plan, other_plan, tic, years):
    """Intake in 2025 follows the 2025 plan, which does not have the TIC track of the 2023 plan."""
    with pytest.raises(ValidationError):
        create_class_group(course, years[2025], track=tic, actor=None)
    assert not ClassGroup.objects.exists()
