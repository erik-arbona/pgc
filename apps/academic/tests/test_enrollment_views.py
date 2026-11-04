"""View tests for the enrollment screens of the Serviços Académicos (T1.3).

Implements: docs/especificacao/02_perfis_e_dados.md – the Serviços Académicos enter the enrollments;
D40 (reason), D50 (UI pattern), D76 (estimated, then real), D81 (a number per turma and year).
The profile has no scope: the action ``enrollment.edit`` is enough.
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
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def years():
    """Academic years 2022 to 2027, by start year."""
    return {y: AcademicYear.objects.create(start_year=y) for y in range(2022, 2028)}


@pytest.fixture
def course():
    """The course EIC."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    return Course.objects.create(faculty=faculty, name="EIC", level="bachelor")


@pytest.fixture
def plan(course, years):
    """The plan that starts in 2023."""
    return StudyPlan.objects.create(course=course, academic_year=years[2023])


@pytest.fixture
def cohort(course, plan, years):
    """The turma that enters in 2023."""
    return ClassGroup.objects.create(course=course, intake_year=years[2023], study_plan=plan)


@pytest.fixture
def services(client):
    """A client logged in as the Serviços Académicos."""
    user = get_user_model().objects.create_user(username="sa", password="x")
    RoleAssignment.objects.create(
        user=user, profile=Profile.ACADEMIC_SERVICES, scope_kind=ScopeKind.NONE, scope_id=None
    )
    client.force_login(user)
    return client


def data(group, year, kind="estimated", students=30, **extra):
    """POST data of the creation form."""
    return {
        "class_group": group.pk,
        "academic_year": year.pk,
        "kind": kind,
        "students": students,
        **extra,
    }


# --- who may reach the screens -----------------------------------------------------------------

URLS = ["academic:enrollment_list", "academic:enrollment_create", "academic:enrollment_pending"]


@pytest.mark.parametrize("name", URLS)
def test_anonymous_visitors_are_redirected_to_login(client, name):
    """Every screen requires a session."""
    response = client.get(reverse(name))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("name", URLS)
@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.ACADEMIC_SERVICES])
def test_other_profiles_get_403(client, make_user, name, profile):
    """Only the Serviços Académicos reach the enrollment screens."""
    client.force_login(make_user(profile))
    assert client.get(reverse(name)).status_code == 403


def test_other_profiles_cannot_write(client, make_user, cohort, years):
    """The server refuses a creation from any other profile."""
    client.force_login(make_user(Profile.PGC_MANAGER))
    response = client.post(reverse("academic:enrollment_create"), data(cohort, years[2023]))
    assert response.status_code == 403 and not Enrollment.objects.exists()


def test_the_menu_shows_the_link_to_the_services_only(client, services, make_user):
    """The link appears for the Serviços Académicos and not for a manager."""
    assert reverse("academic:enrollment_list") in services.get("/").content.decode()
    client.logout()
    client.force_login(make_user(Profile.PGC_MANAGER, "gestor"))
    assert reverse("academic:enrollment_list") not in client.get("/").content.decode()


# --- creating ----------------------------------------------------------------------------------


def test_an_estimated_number_is_created_audited_and_marked_manual(services, cohort, years):
    """The number is saved as typed, with the actor in the audit log."""
    response = services.post(reverse("academic:enrollment_create"), data(cohort, years[2023]))
    assert response.status_code == 302
    row = Enrollment.objects.get()
    assert (row.students, row.kind, row.source) == (30, "estimated", "manual")
    entry = AuditEntry.objects.get(entity="academic.enrollment")
    assert (entry.action, entry.actor.username, entry.new_value["students"]) == ("create", "sa", 30)


def test_the_real_number_is_created_next_to_the_estimate(services, cohort, years):
    """Both kinds can exist for the same turma and year (D76)."""
    for kind, students in (("estimated", 30), ("actual", 27)):
        services.post(
            reverse("academic:enrollment_create"), data(cohort, years[2023], kind, students)
        )
    assert set(Enrollment.objects.values_list("kind", "students")) == {
        ("estimated", 30),
        ("actual", 27),
    }


def test_a_year_in_which_the_turma_does_not_exist_is_a_field_error(services, cohort, years):
    """The turma enters in 2023: there is nothing to count in 2022."""
    response = services.post(reverse("academic:enrollment_create"), data(cohort, years[2022]))
    assert response.status_code == 200
    assert "academic_year" in response.context["form"].errors
    assert not Enrollment.objects.exists()


def test_a_second_number_of_the_same_kind_is_a_form_error_not_a_server_error(
    services, cohort, years
):
    """One estimate and one real number per turma and year."""
    services.post(reverse("academic:enrollment_create"), data(cohort, years[2023]))
    response = services.post(reverse("academic:enrollment_create"), data(cohort, years[2023]))
    assert response.status_code == 200 and response.context["form"].errors
    assert Enrollment.objects.count() == 1


def test_a_negative_number_is_a_form_error(services, cohort, years):
    """Students cannot be negative."""
    response = services.post(
        reverse("academic:enrollment_create"), data(cohort, years[2023], students=-3)
    )
    assert response.status_code == 200 and "students" in response.context["form"].errors


def test_the_creation_form_can_be_prefilled_from_the_link(services, cohort, years):
    """The pending list links here with the turma and the year already chosen."""
    url = reverse("academic:enrollment_create")
    response = services.get(f"{url}?class_group={cohort.pk}&academic_year={years[2023].pk}")
    initial = response.context["form"].initial
    assert (initial["class_group"], initial["academic_year"]) == (cohort.pk, years[2023].pk)


# --- correcting and deleting -------------------------------------------------------------------


def make_row(group, year, kind="estimated", students=30, source="manual"):
    """Create an enrollment row."""
    return Enrollment.objects.create(
        class_group=group, academic_year=year, kind=kind, students=students, source=source
    )


def test_correcting_a_number_needs_a_reason_and_is_audited(services, cohort, years):
    """No reason: refused. With a reason: updated, with the old and new values."""
    row = make_row(cohort, years[2023])
    url = reverse("academic:enrollment_update", kwargs={"pk": row.pk})
    services.post(url, {"students": 28, "reason": ""})
    row.refresh_from_db()
    assert row.students == 30 and not AuditEntry.objects.filter(action="update").exists()
    services.post(url, {"students": 28, "reason": "Número confirmado"})
    row.refresh_from_db()
    assert row.students == 28
    entry = AuditEntry.objects.get(action="update")
    assert (entry.old_value["students"], entry.new_value["students"]) == (30, 28)
    assert entry.reason == "Número confirmado"


def test_only_the_number_can_be_corrected(services, cohort, years):
    """The turma, the year and the kind are fixed; delete and create again to change them."""
    row = make_row(cohort, years[2023])
    response = services.get(reverse("academic:enrollment_update", kwargs={"pk": row.pk}))
    fields = set(response.context["form"].fields)
    assert fields - {"reason", "reason_choice"} == {"students"}


def test_a_number_corrected_by_hand_is_marked_manual(services, cohort, years):
    """A number from the SII that a person corrects no longer matches the SII."""
    row = make_row(cohort, years[2023], kind="actual", source="sii")
    services.post(
        reverse("academic:enrollment_update", kwargs={"pk": row.pk}),
        {"students": 25, "reason": "Corrigido"},
    )
    row.refresh_from_db()
    assert (row.students, row.source) == (25, "manual")


def test_deleting_a_number_needs_a_reason_and_is_audited(services, cohort, years):
    """Deletion asks for a reason and is logged."""
    row = make_row(cohort, years[2023])
    url = reverse("academic:enrollment_delete", kwargs={"pk": row.pk})
    services.post(url, {"reason": ""})
    assert Enrollment.objects.exists()
    services.post(url, {"reason": "Engano"})
    assert not Enrollment.objects.exists()
    assert AuditEntry.objects.get(action="delete").entity == "academic.enrollment"


# --- the list ----------------------------------------------------------------------------------


def test_the_list_shows_the_numbers_with_turma_year_and_kind(services, cohort, years):
    """Each row names the course, the turma, the year, the kind, the number and the origin."""
    make_row(cohort, years[2023], "estimated", 31)
    page = services.get(reverse("academic:enrollment_list")).content.decode()
    assert "EIC" in page and "2023" in page and "31" in page and "Estimada" in page


def test_the_list_filters_by_year_course_and_kind(services, course, plan, cohort, years):
    """The three filters narrow the list."""
    other_course = Course.objects.create(faculty=course.faculty, name="TM", level="bachelor")
    other_plan = StudyPlan.objects.create(course=other_course, academic_year=years[2023])
    tm = ClassGroup.objects.create(
        course=other_course, intake_year=years[2023], study_plan=other_plan
    )
    second = ClassGroup.objects.create(
        course=course, intake_year=years[2024], study_plan=plan, label="B"
    )
    make_row(cohort, years[2023], "estimated", 31)
    make_row(cohort, years[2023], "actual", 32)
    make_row(tm, years[2023], "estimated", 33)
    make_row(second, years[2024], "estimated", 34)
    url = reverse("academic:enrollment_list")

    def numbers(query):
        response = services.get(f"{url}?{query}")
        return {row.students for row in response.context["object_list"]}

    assert numbers("") == {31, 32, 33, 34}
    assert numbers(f"academic_year={years[2024].pk}") == {34}
    assert numbers(f"course={other_course.pk}") == {33}
    assert numbers("kind=actual") == {32}
    assert numbers(f"academic_year={years[2023].pk}&kind=estimated&course={course.pk}") == {31}


def test_an_htmx_request_returns_only_the_results(services, cohort, years):
    """The fragment has the table and not the whole page (D50)."""
    make_row(cohort, years[2023])
    response = services.get(reverse("academic:enrollment_list"), HTTP_HX_REQUEST="true")
    page = response.content.decode()
    assert "<table" in page and "<html" not in page


# --- the turmas that still have no number ------------------------------------------------------


def test_the_pending_list_shows_the_turmas_of_the_year_with_no_number(
    services, course, plan, cohort, years
):
    """The cohort turma exists in 2023 and has no number yet."""
    url = reverse("academic:enrollment_pending")
    response = services.get(f"{url}?academic_year={years[2023].pk}")
    assert [row["group"] for row in response.context["rows"]] == [cohort]
    page = response.content.decode()
    assert f"class_group={cohort.pk}" in page and f"academic_year={years[2023].pk}" in page


def test_a_turma_with_any_number_that_year_is_not_pending(services, cohort, years):
    """An estimate is enough to leave the list; the real one is the update that follows."""
    make_row(cohort, years[2023], "estimated")
    url = reverse("academic:enrollment_pending")
    response = services.get(f"{url}?academic_year={years[2023].pk}")
    assert response.context["rows"] == []


def test_a_turma_that_does_not_exist_that_year_is_not_pending(services, cohort, years):
    """The turma enters in 2023, so it is not pending in 2022."""
    url = reverse("academic:enrollment_pending")
    response = services.get(f"{url}?academic_year={years[2022].pk}")
    assert response.context["rows"] == []


def test_the_pending_list_follows_the_tracks_of_the_fourth_year(
    services, course, plan, cohort, years
):
    """In 2026 the cohort turma no longer exists and the track turmas do (D79)."""
    tic = Track.objects.create(study_plan=plan, code="TIC", name="TIC", first_curricular_year=4)
    psi = Track.objects.create(study_plan=plan, code="PSI", name="PSI", first_curricular_year=4)
    tic_turma = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, track=tic
    )
    psi_turma = ClassGroup.objects.create(
        course=course, intake_year=years[2023], study_plan=plan, track=psi
    )
    url = reverse("academic:enrollment_pending")
    in_2026 = services.get(f"{url}?academic_year={years[2026].pk}").context["rows"]
    assert [row["group"] for row in in_2026] == [psi_turma, tic_turma]
    assert cohort not in [row["group"] for row in in_2026]
    in_2025 = services.get(f"{url}?academic_year={years[2025].pk}").context["rows"]
    assert [row["group"] for row in in_2025] == [cohort]


def test_the_pending_list_defaults_to_the_latest_academic_year(services, cohort, years):
    """Without a year in the query it uses the most recent academic year."""
    response = services.get(reverse("academic:enrollment_pending"))
    assert response.context["selected_year"] == years[2027]
