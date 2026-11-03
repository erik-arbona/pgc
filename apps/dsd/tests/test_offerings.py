"""Tests for generating the offerings of a DSD semester (T2.3).

Implements: docs/backlog_fase2.md T2.3; D48, D49 (a turma follows its plan and its curricular
year), D79 (tracks), D81 (sizes), D86 (state of the cell), D87 (generation).
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse

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
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.dsd.models import Offering, OfferingClassGroup
from apps.dsd.services import change_state, create_dsd, generate_offerings

pytestmark = pytest.mark.django_db


@pytest.fixture
def years():
    """Academic years 2023 to 2028, by start year."""
    return {y: AcademicYear.objects.create(start_year=y) for y in range(2023, 2029)}


@pytest.fixture
def faculty():
    """The Faculty of the course and of its coordination."""
    return Faculty.objects.create(name="Faculdade A", code="FA")


@pytest.fixture
def coordination(faculty):
    """The coordination that owns the subjects."""
    return Coordination.objects.create(faculty=faculty, name="Coordenação A")


@pytest.fixture
def plan(faculty, years):
    """The plan of EIC, in force since 2023."""
    course = Course.objects.create(faculty=faculty, name="EIC", level="bachelor")
    return StudyPlan.objects.create(course=course, academic_year=years[2023])


@pytest.fixture
def manager(django_user_model, faculty):
    """A PGC manager of the Faculty."""
    user = django_user_model.objects.create_user(username="mgr", password="x")
    RoleAssignment.objects.create(
        user=user, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.FACULTY, scope_id=faculty.pk
    )
    return user


@pytest.fixture
def dsd(manager, years):
    """The DSD of 2026-2027."""
    return create_dsd(years[2026], manager)


@pytest.fixture
def s1(dsd):
    """The 1st semester of the DSD."""
    return dsd.semesters.get(number=1)


@pytest.fixture
def s2(dsd):
    """The 2nd semester of the DSD."""
    return dsd.semesters.get(number=2)


def subject(plan, coordination, code, curricular_year=1, semester=1, **extra):
    """A valid subject of the plan."""
    data = dict(
        study_plan=plan,
        code=code,
        name=f"Disciplina {code}",
        ects=Decimal("6"),
        curricular_year=curricular_year,
        semester=semester,
        coordination=coordination,
        semester_hours=Decimal("75"),
    )
    data.update(extra)
    return Subject.objects.create(**data)


def turma(plan, intake, **extra):
    """A turma of the plan's course entering in the academic year ``intake``."""
    return ClassGroup.objects.create(
        course=plan.course, intake_year=intake, study_plan=plan, **extra
    )


def links(offering):
    """The turmas that take an offering."""
    return {link.class_group for link in offering.class_group_links.all()}


# --- what is offered ---------------------------------------------------------------------------


def test_a_turma_takes_the_subjects_of_its_curricular_year_and_semester(
    manager, plan, coordination, years, s1, s2
):
    """In 2026 the turma that entered in 2026 is in year 1: only year 1 of the semester."""
    group = turma(plan, years[2026])
    wanted = subject(plan, coordination, "A1", 1, 1)
    subject(plan, coordination, "A2", 1, 2)
    subject(plan, coordination, "B1", 2, 1)
    result = generate_offerings(manager, [s1])
    assert (result.created_offerings, result.created_links) == (1, 1)
    offering = Offering.objects.get()
    assert (offering.subject, offering.dsd_semester) == (wanted, s1)
    assert links(offering) == {group}


def test_the_second_semester_gets_its_own_offerings(manager, plan, coordination, years, s1, s2):
    """The same call for both semesters creates each subject in its semester."""
    turma(plan, years[2026])
    subject(plan, coordination, "A1", 1, 1)
    second = subject(plan, coordination, "A2", 1, 2)
    generate_offerings(manager, [s1, s2])
    assert Offering.objects.filter(dsd_semester=s2).get().subject == second
    assert Offering.objects.count() == 2


def test_two_turmas_of_the_year_share_one_offering(manager, plan, coordination, years, s1):
    """A and B are two turmas of the same course and plan: one offering, two links."""
    a = turma(plan, years[2026], label="A")
    b = turma(plan, years[2026], label="B")
    subject(plan, coordination, "A1")
    generate_offerings(manager, [s1])
    assert Offering.objects.count() == 1
    assert links(Offering.objects.get()) == {a, b}


def test_turmas_of_different_years_take_different_subjects(manager, plan, coordination, years, s1):
    """The 2025 intake is in year 2 in 2026; the 2026 intake in year 1."""
    old = turma(plan, years[2025])
    new = turma(plan, years[2026])
    first = subject(plan, coordination, "A1", 1, 1)
    second = subject(plan, coordination, "B1", 2, 1)
    generate_offerings(manager, [s1])
    assert links(Offering.objects.get(subject=first)) == {new}
    assert links(Offering.objects.get(subject=second)) == {old}


def test_a_turma_that_has_not_entered_or_has_ended_takes_nothing(
    manager, plan, coordination, years, s1
):
    """Future intake and ended turmas are not in the DSD of 2026."""
    turma(plan, years[2027])
    turma(plan, years[2023], last_academic_year=years[2024], label="B")
    subject(plan, coordination, "A1", 1, 1)
    subject(plan, coordination, "C1", 3, 1)
    result = generate_offerings(manager, [s1])
    assert result.created_offerings == 0 and not Offering.objects.exists()


def test_track_turmas_take_the_common_and_their_own_subjects(
    manager, plan, coordination, years, s1
):
    """In the 4th year the cohort turma stops and the TIC and PSI turmas take their subjects."""
    cohort = turma(plan, years[2023])
    tic = Track.objects.create(study_plan=plan, code="TIC", name="TIC", first_curricular_year=4)
    psi = Track.objects.create(study_plan=plan, code="PSI", name="PSI", first_curricular_year=4)
    tic_turma = turma(plan, years[2023], track=tic)
    psi_turma = turma(plan, years[2023], track=psi)
    common = subject(plan, coordination, "C4", 4, 1)
    only_tic = subject(plan, coordination, "T4", 4, 1, track=tic)
    only_psi = subject(plan, coordination, "P4", 4, 1, track=psi)
    # The DSD of 2026-2027 is the 4th year of the 2023 intake.
    generate_offerings(manager, [s1])
    assert links(Offering.objects.get(subject=common)) == {tic_turma, psi_turma}
    assert links(Offering.objects.get(subject=only_tic)) == {tic_turma}
    assert links(Offering.objects.get(subject=only_psi)) == {psi_turma}
    assert cohort not in {link.class_group for link in OfferingClassGroup.objects.all()}


# --- running it again --------------------------------------------------------------------------


def test_running_it_again_creates_nothing(manager, plan, coordination, years, s1):
    """The second run finds everything in place."""
    turma(plan, years[2026])
    subject(plan, coordination, "A1")
    generate_offerings(manager, [s1])
    again = generate_offerings(manager, [s1])
    assert (again.created_offerings, again.created_links) == (0, 0)
    assert Offering.objects.count() == 1 and OfferingClassGroup.objects.count() == 1


def test_a_turma_or_subject_added_later_is_added_without_touching_the_rest(
    manager, plan, coordination, years, s1
):
    """Only the missing link and the missing offering are created."""
    first = turma(plan, years[2026], label="A")
    subject(plan, coordination, "A1")
    generate_offerings(manager, [s1])
    offering = Offering.objects.get()
    version = offering.version
    second = turma(plan, years[2026], label="B")
    subject(plan, coordination, "A3")
    result = generate_offerings(manager, [s1])
    assert (result.created_offerings, result.created_links) == (1, 3)
    offering.refresh_from_db()
    assert offering.version == version and links(offering) == {first, second}


def test_what_is_no_longer_called_for_is_reported_and_kept(manager, plan, coordination, years, s1):
    """A turma that ends keeps its history: the link and the offering stay, flagged as stale."""
    group = turma(plan, years[2023])
    subject(plan, coordination, "A4", 4, 1)
    generate_offerings(manager, [s1])
    group.last_academic_year = years[2025]
    group.save()
    result = generate_offerings(manager, [s1])
    assert (result.stale_offerings, result.stale_links) == (1, 0)
    assert Offering.objects.count() == 1 and OfferingClassGroup.objects.count() == 1


def test_a_link_to_a_turma_no_longer_taking_the_subject_is_stale(
    manager, plan, coordination, years, s1
):
    """The offering is still wanted (another turma takes it) but one link is not."""
    old = turma(plan, years[2023], label="A")
    turma(plan, years[2023], label="B")
    subject(plan, coordination, "A4", 4, 1)
    generate_offerings(manager, [s1])
    old.last_academic_year = years[2025]
    old.save()
    result = generate_offerings(manager, [s1])
    assert (result.stale_offerings, result.stale_links) == (0, 1)
    assert OfferingClassGroup.objects.count() == 2


# --- state of the cell, scope and audit --------------------------------------------------------


def test_a_closed_cell_is_skipped_and_reported(manager, plan, coordination, years, s1):
    """Closed means read-only: nothing is created and the cell is reported."""
    turma(plan, years[2026])
    subject(plan, coordination, "A1")
    change_state(manager, "open", [s1], [coordination])
    change_state(manager, "close", [s1], [coordination], reason="done")
    result = generate_offerings(manager, [s1])
    assert result.blocked == [(s1, coordination.pk)] and not Offering.objects.exists()


def test_a_cell_not_opened_and_an_open_cell_accept_generation(
    manager, plan, coordination, years, s1, s2
):
    """The manager prepares the offerings before opening the semester (D86)."""
    turma(plan, years[2026])
    subject(plan, coordination, "A1", 1, 1)
    subject(plan, coordination, "A2", 1, 2)
    change_state(manager, "open", [s2], [coordination])
    result = generate_offerings(manager, [s1, s2])
    assert result.created_offerings == 2 and result.blocked == []


def test_a_closed_cell_does_not_block_the_other_coordinations(
    manager, plan, coordination, faculty, years, s1
):
    """Each coordination is its own cell."""
    other = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    turma(plan, years[2026])
    subject(plan, coordination, "A1")
    kept = subject(plan, other, "B1")
    change_state(manager, "open", [s1], [coordination])
    change_state(manager, "close", [s1], [coordination], reason="done")
    result = generate_offerings(manager, [s1])
    assert Offering.objects.get().subject == kept and len(result.blocked) == 1


def test_a_coordination_of_another_faculty_is_out_of_scope(manager, plan, coordination, years, s1):
    """The manager of Faculty A does not generate for a coordination of Faculty B (D69)."""
    foreign = Coordination.objects.create(
        faculty=Faculty.objects.create(name="Faculdade B", code="FB"), name="Coordenação X"
    )
    turma(plan, years[2026])
    subject(plan, coordination, "A1")
    subject(plan, foreign, "X1")
    result = generate_offerings(manager, [s1])
    assert result.out_of_scope == [(s1, foreign.pk)]
    assert Offering.objects.get().subject.coordination == coordination


def test_the_coordinations_can_be_limited(manager, plan, coordination, faculty, years, s1):
    """Asking for one coordination leaves the others alone."""
    other = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    turma(plan, years[2026])
    subject(plan, coordination, "A1")
    subject(plan, other, "B1")
    generate_offerings(manager, [s1], [other.pk])
    assert Offering.objects.get().subject.coordination == other


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_only_a_manager_generates(make_user, plan, coordination, years, s1, profile):
    """Coordinator, board and the others cover no coordination for this action."""
    turma(plan, years[2026])
    subject(plan, coordination, "A1")
    with pytest.raises(PermissionDenied):
        generate_offerings(make_user(profile), [s1])
    assert not Offering.objects.exists()


def test_every_new_row_is_audited_with_the_actor_and_reason(manager, plan, coordination, years, s1):
    """One entry for each offering and each link."""
    turma(plan, years[2026])
    subject(plan, coordination, "A1")
    generate_offerings(manager, [s1], reason="start of the year")
    entries = AuditEntry.objects.filter(actor=manager)
    assert entries.filter(entity="dsd.offering").count() == 1
    assert entries.filter(entity="dsd.offeringclassgroup").count() == 1
    assert {e.reason for e in entries.filter(entity__startswith="dsd.offering")} == {
        "start of the year"
    }


# --- the models --------------------------------------------------------------------------------


def test_an_offering_cannot_be_saved_outside_the_guard(plan, coordination, s1):
    """DSD data is written inside ``dsd_write`` only."""
    with pytest.raises(ImproperlyConfigured):
        Offering(dsd_semester=s1, subject=subject(plan, coordination, "A1")).save()


def test_an_offering_needs_the_subject_to_be_of_that_semester(plan, coordination, s1):
    """A 2nd-semester subject cannot be offered in the 1st semester."""
    with pytest.raises(ValidationError):
        Offering(dsd_semester=s1, subject=subject(plan, coordination, "A2", 1, 2)).clean()


def test_a_subject_is_offered_once_per_semester(manager, plan, coordination, years, s1):
    """The database refuses a second offering of the same subject in the semester."""
    turma(plan, years[2026])
    item = subject(plan, coordination, "A1")
    generate_offerings(manager, [s1])
    with pytest.raises(IntegrityError), transaction.atomic():
        Offering.objects.bulk_create([Offering(dsd_semester=s1, subject=item)])


def test_a_turma_with_offerings_cannot_be_deleted(manager, plan, coordination, years, s1):
    """The history of the DSD protects the turma (D54)."""
    group = turma(plan, years[2026])
    subject(plan, coordination, "A1")
    generate_offerings(manager, [s1])
    with pytest.raises(ProtectedError):
        group.delete()


# --- the screens -------------------------------------------------------------------------------


def test_the_generate_form_creates_the_offerings(client, manager, plan, coordination, years, dsd):
    """Posting both semesters and all coordinations."""
    turma(plan, years[2026])
    subject(plan, coordination, "A1", 1, 1)
    subject(plan, coordination, "A2", 1, 2)
    client.force_login(manager)
    response = client.post(
        reverse("dsd:offering_generate", args=[dsd.pk]),
        {"semester": "both", "coordination": "", "reason": ""},
    )
    assert response.status_code == 302 and Offering.objects.count() == 2


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403_on_the_generate_form(client, make_user, dsd, profile):
    """Also for a DSD that does not exist: nobody learns what exists."""
    client.force_login(make_user(profile))
    assert client.get(reverse("dsd:offering_generate", args=[dsd.pk])).status_code == 403
    assert client.get(reverse("dsd:offering_generate", args=[dsd.pk + 999])).status_code == 403
    assert client.post(reverse("dsd:offering_generate", args=[dsd.pk]), {}).status_code == 403


def test_the_form_offers_only_the_coordinations_the_manager_covers(
    client, manager, coordination, dsd
):
    """A coordination of another Faculty is not a choice."""
    foreign = Coordination.objects.create(
        faculty=Faculty.objects.create(name="Faculdade B", code="FB"), name="Coordenação X"
    )
    client.force_login(manager)
    form = client.get(reverse("dsd:offering_generate", args=[dsd.pk])).context["form"]
    assert list(form.fields["coordination"].queryset) == [coordination]
    assert foreign not in form.fields["coordination"].queryset


@pytest.mark.parametrize("profile", [Profile.PGC_MANAGER, Profile.COORDINATOR])
def test_manager_and_coordinator_read_the_offerings(
    client, make_user, plan, coordination, years, dsd, s1, manager, profile
):
    """The list shows the subject, the turmas and their size, provisional when estimated."""
    group = turma(plan, years[2026])
    subject(plan, coordination, "A1")
    Enrollment.objects.create(
        class_group=group, academic_year=years[2026], kind="estimated", students=31
    )
    generate_offerings(manager, [s1])
    client.force_login(make_user(profile, f"u-{profile}"))
    page = client.get(reverse("dsd:offering_list", args=[dsd.pk])).content.decode()
    assert "Disciplina A1" in page and "31" in page and "provisório" in page


def test_a_turma_without_a_number_says_so(client, manager, plan, coordination, years, dsd, s1):
    """The offering is listed with 'sem matrícula'."""
    turma(plan, years[2026])
    subject(plan, coordination, "A1")
    generate_offerings(manager, [s1])
    client.force_login(manager)
    page = client.get(reverse("dsd:offering_list", args=[dsd.pk])).content.decode()
    assert "sem matrícula" in page


def test_the_list_can_be_filtered_by_semester_and_coordination(
    client, manager, plan, coordination, faculty, years, dsd, s1, s2
):
    """Each filter keeps only its offerings."""
    other = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    turma(plan, years[2026])
    first = subject(plan, coordination, "A1", 1, 1)
    subject(plan, coordination, "A2", 1, 2)
    third = subject(plan, other, "B1", 1, 1)
    generate_offerings(manager, [s1, s2])
    client.force_login(manager)
    url = reverse("dsd:offering_list", args=[dsd.pk])
    by_semester = client.get(f"{url}?semester=1").context["rows"]
    assert {o.subject for o, _ in by_semester} == {first, third}
    by_coordination = client.get(f"{url}?semester=1&coordination={other.pk}").context["rows"]
    assert [o.subject for o, _ in by_coordination] == [third]


def test_the_coordinator_is_not_offered_the_generate_link(
    client, make_user, dsd, manager, coordination
):
    """Only who can generate sees the link."""
    url = reverse("dsd:offering_list", args=[dsd.pk])
    generate = reverse("dsd:offering_generate", args=[dsd.pk])
    client.force_login(make_user(Profile.COORDINATOR, "c"))
    assert generate not in client.get(url).content.decode()
    client.logout()
    client.force_login(manager)
    assert generate in client.get(url).content.decode()


def test_other_profiles_do_not_read_the_offerings(client, make_user, dsd):
    """The list needs ``dsd.view``."""
    client.force_login(make_user(Profile.TEACHER, "t"))
    assert client.get(reverse("dsd:offering_list", args=[dsd.pk])).status_code == 403
