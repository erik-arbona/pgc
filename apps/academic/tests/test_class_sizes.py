"""Tests for the size of each turma, read by the coordinator (T1.5).

Implements: docs/especificacao/02_perfis_e_dados.md – the coordinator sees the size of each
turma, which results from the enrollments; D49 and D79 (which turmas exist in a year), D76 (the
real number replaces the estimate), D84 (the coordinator reads every turma, and only reads).
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    Course,
    Enrollment,
    Faculty,
    StudyPlan,
    Track,
)
from apps.academic.services import class_group_size_rows
from apps.core.models import Profile, RoleAssignment, ScopeKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def years():
    """Academic years 2022 to 2027, by start year."""
    return {y: AcademicYear.objects.create(start_year=y) for y in range(2022, 2028)}


def make_course(code, name):
    """A course in its own Faculty, with a plan that starts in 2023."""
    faculty = Faculty.objects.create(name=f"Faculdade {code}", code=code)
    course = Course.objects.create(faculty=faculty, name=name, level="bachelor")
    year, _ = AcademicYear.objects.get_or_create(start_year=2023)
    plan = StudyPlan.objects.create(course=course, academic_year=year)
    return course, plan


@pytest.fixture
def eic(years):
    """The course EIC with its plan."""
    return make_course("FA", "EIC")


@pytest.fixture
def tm(years):
    """The course TM, in another Faculty."""
    return make_course("FB", "TM")


def group(course_and_plan, year, **extra):
    """A turma entering in ``year``."""
    course, plan = course_and_plan
    return ClassGroup.objects.create(course=course, intake_year=year, study_plan=plan, **extra)


def number(turma, year, kind, students):
    """An enrollment number."""
    return Enrollment.objects.create(
        class_group=turma, academic_year=year, kind=kind, students=students
    )


@pytest.fixture
def coordinator(client):
    """A client logged in as a coordinator."""
    user = get_user_model().objects.create_user(username="coord", password="x")
    RoleAssignment.objects.create(
        user=user, profile=Profile.COORDINATOR, scope_kind=ScopeKind.COORDINATION, scope_id=999_999
    )
    client.force_login(user)
    return client


# --- the service -------------------------------------------------------------------------------


def test_an_estimate_alone_is_provisional(eic, years):
    """Only an estimate: it counts, marked provisional, and there is no change yet."""
    turma = group(eic, years[2023])
    number(turma, years[2023], "estimated", 30)
    (row,) = class_group_size_rows(years[2023])
    assert (row.estimated, row.actual, row.change) == (30, None, None)
    assert (row.effective.students, row.effective.provisional) == (30, True)
    assert (row.group, row.curricular_year) == (turma, 1)


def test_the_real_number_replaces_the_estimate_and_gives_the_change(eic, years):
    """Both numbers: the real one counts and the change is real minus estimated (D76)."""
    turma = group(eic, years[2023])
    number(turma, years[2023], "estimated", 30)
    number(turma, years[2023], "actual", 27)
    (row,) = class_group_size_rows(years[2023])
    assert (row.estimated, row.actual, row.change) == (30, 27, -3)
    assert (row.effective.students, row.effective.provisional) == (27, False)


def test_a_turma_with_no_number_is_listed_without_a_size(eic, years):
    """It exists that year but nobody has entered a number."""
    group(eic, years[2023])
    (row,) = class_group_size_rows(years[2023])
    assert (row.estimated, row.actual, row.effective, row.change) == (None, None, None, None)


def test_only_the_turmas_that_exist_in_the_year_are_listed(eic, years):
    """A turma that enters in 2024 is not listed in 2023; the 2023 one is in its 2nd year."""
    first = group(eic, years[2023])
    second = group(eic, years[2024], label="B")
    in_2023 = class_group_size_rows(years[2023])
    in_2024 = class_group_size_rows(years[2024])
    assert [r.group for r in in_2023] == [first]
    assert {(r.group, r.curricular_year) for r in in_2024} == {(first, 2), (second, 1)}


def test_the_track_turmas_replace_the_cohort_turma_in_the_fourth_year(eic, years):
    """In 2026 the cohort turma no longer exists and the TIC and PSI turmas do (D79)."""
    course, plan = eic
    cohort = group(eic, years[2023])
    for code in ("TIC", "PSI"):
        track = Track.objects.create(study_plan=plan, code=code, name=code, first_curricular_year=4)
        group(eic, years[2023], track=track)
    in_2026 = class_group_size_rows(years[2026])
    assert {r.group.track.code for r in in_2026} == {"TIC", "PSI"}
    assert all(r.curricular_year == 4 for r in in_2026)
    assert cohort not in [r.group for r in in_2026]


def test_the_rows_can_be_limited_to_a_course(eic, tm, years):
    """The course filter keeps only the turmas of that course."""
    group(eic, years[2023])
    other = group(tm, years[2023])
    rows = class_group_size_rows(years[2023], course=tm[0])
    assert [r.group for r in rows] == [other]


# --- the screen --------------------------------------------------------------------------------

URL = "academic:classsize_list"


def test_anonymous_visitors_are_redirected_to_login(client):
    """The screen requires a session."""
    response = client.get(reverse(URL))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.COORDINATOR])
def test_other_profiles_get_403(client, make_user, profile):
    """Only the coordinator reads the sizes here (D84)."""
    client.force_login(make_user(profile))
    assert client.get(reverse(URL)).status_code == 403


def test_the_coordinator_reads_the_turmas_of_every_course_and_faculty(coordinator, eic, tm, years):
    """The coordinator sees all the turmas, not only those of their own coordination (D84)."""
    a = group(eic, years[2023])
    b = group(tm, years[2023])
    response = coordinator.get(f"{reverse(URL)}?academic_year={years[2023].pk}")
    assert [r.group for r in response.context["rows"]] == [a, b]


def test_the_screen_shows_the_numbers_the_mark_and_the_change(coordinator, eic, tm, years):
    """Estimated, real, the number that counts, 'provisional' and the change."""
    estimated_only = group(eic, years[2023])
    both = group(tm, years[2023])
    number(estimated_only, years[2023], "estimated", 31)
    number(both, years[2023], "estimated", 30)
    number(both, years[2023], "actual", 27)
    page = coordinator.get(f"{reverse(URL)}?academic_year={years[2023].pk}").content.decode()
    assert "31" in page and "27" in page and "-3" in page
    assert "provisório" in page.lower()


def test_a_turma_without_a_number_says_so(coordinator, eic, years):
    """The row is there with 'sem matrícula'."""
    group(eic, years[2023])
    page = coordinator.get(f"{reverse(URL)}?academic_year={years[2023].pk}").content.decode()
    assert "sem matrícula" in page.lower()


def test_the_course_filter_limits_the_screen(coordinator, eic, tm, years):
    """Choosing a course shows only its turmas."""
    group(eic, years[2023])
    other = group(tm, years[2023])
    url = f"{reverse(URL)}?academic_year={years[2023].pk}&course={tm[0].pk}"
    assert [r.group for r in coordinator.get(url).context["rows"]] == [other]


def test_the_year_defaults_to_the_latest_academic_year(coordinator, eic, years):
    """Without a year in the query the most recent academic year is used."""
    group(eic, years[2023])
    response = coordinator.get(reverse(URL))
    assert response.context["selected_year"] == years[2027]


def test_the_screen_is_read_only(coordinator, eic, years):
    """Posting to it is refused: the numbers are entered by the Serviços Académicos."""
    turma = group(eic, years[2023])
    response = coordinator.post(
        reverse(URL), {"class_group": turma.pk, "academic_year": years[2023].pk, "students": 5}
    )
    assert response.status_code == 405 and not Enrollment.objects.exists()


def test_the_menu_shows_the_link_to_the_coordinator_only(coordinator, make_user, client):
    """The link appears for the coordinator and not for the Serviços Académicos."""
    assert reverse(URL) in coordinator.get("/").content.decode()
    client.logout()
    client.force_login(make_user(Profile.ACADEMIC_SERVICES, "sa"))
    assert reverse(URL) not in client.get("/").content.decode()
