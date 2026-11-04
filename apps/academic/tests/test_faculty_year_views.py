"""View tests for the Faculty and academic year screens (T2.6, part 2).

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1, data entered by the
PGC manager; D40 (reason), D50 (UI pattern).
"""

import pytest
from django.urls import reverse

from apps.academic.models import AcademicYear, Coordination, Course, Faculty, StudyPlan
from apps.core.models import AuditEntry, Profile
from apps.core.permissions import can

pytestmark = pytest.mark.django_db

SCREENS = ["faculty", "academicyear"]


@pytest.mark.parametrize("screen", SCREENS)
def test_anonymous_visitors_are_redirected_to_login(client, screen):
    """Both lists require a session."""
    response = client.get(reverse(f"academic:{screen}_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, screen, profile):
    """Only the PGC manager reaches these screens, on GET and on POST."""
    client.force_login(make_user(profile))
    for name in ("list", "create"):
        url = reverse(f"academic:{screen}_{name}")
        assert client.get(url).status_code == 403
        assert client.post(url, {"name": "X", "code": "X", "start_year": 2030}).status_code == 403
    assert not Faculty.objects.exists()
    assert not AcademicYear.objects.exists()
    assert not AuditEntry.objects.exists()


@pytest.mark.parametrize("profile", list(Profile))
def test_only_the_pgc_manager_has_the_new_actions(make_user, profile):
    """faculty.edit and academic_year.edit belong to the PGC manager alone."""
    user = make_user(profile)
    expected = profile == Profile.PGC_MANAGER
    assert can(user, "faculty.edit") is expected
    assert can(user, "academic_year.edit") is expected


def test_creating_a_faculty_is_audited(manager_client):
    """A new Faculty leaves one audit entry with the actor."""
    manager_client.post(reverse("academic:faculty_create"), {"name": "Faculdade X", "code": "FX"})
    faculty = Faculty.objects.get(code="FX")
    entry = AuditEntry.objects.get()
    assert (entry.action, entry.entity_id, entry.actor.username) == (
        "create",
        str(faculty.pk),
        "gestor",
    )


def test_a_duplicate_faculty_code_is_shown_as_a_form_error(manager_client):
    """The unique code is reported on the form and nothing is saved."""
    Faculty.objects.create(name="A", code="FA")
    response = manager_client.post(reverse("academic:faculty_create"), {"name": "B", "code": "FA"})
    assert response.status_code == 200
    assert "code" in response.context["form"].errors
    assert Faculty.objects.count() == 1
    assert not AuditEntry.objects.exists()


def test_editing_a_faculty_needs_a_reason_and_is_audited(manager_client):
    """No reason: refused. With reason: updated with old and new values."""
    faculty = Faculty.objects.create(name="Velho", code="FV")
    url = reverse("academic:faculty_update", kwargs={"pk": faculty.pk})
    manager_client.post(url, {"name": "Novo", "code": "FV", "reason": ""})
    faculty.refresh_from_db()
    assert faculty.name == "Velho" and not AuditEntry.objects.exists()
    manager_client.post(url, {"name": "Novo", "code": "FV", "reason": "Mudou o nome"})
    entry = AuditEntry.objects.get()
    assert (entry.old_value["name"], entry.new_value["name"]) == ("Velho", "Novo")
    assert entry.reason == "Mudou o nome"


def test_deleting_an_unused_faculty_is_audited(manager_client):
    """An unused Faculty can be deleted with a reason."""
    faculty = Faculty.objects.create(name="Vazia", code="FZ")
    manager_client.post(
        reverse("academic:faculty_delete", kwargs={"pk": faculty.pk}), {"reason": "Engano"}
    )
    assert not Faculty.objects.exists()
    assert AuditEntry.objects.get().action == "delete"


def test_deleting_a_faculty_in_use_shows_a_message(manager_client):
    """A Faculty with coordinations is kept; the user is told it is in use."""
    faculty = Faculty.objects.create(name="Cheia", code="FC")
    Coordination.objects.create(faculty=faculty, name="Inf")
    response = manager_client.post(
        reverse("academic:faculty_delete", kwargs={"pk": faculty.pk}),
        {"reason": "Teste"},
        follow=True,
    )
    assert Faculty.objects.exists()
    assert "em uso" in response.content.decode()
    assert not AuditEntry.objects.exists()


def test_the_faculty_list_shows_code_and_name(manager_client):
    """The list prints each Faculty."""
    Faculty.objects.create(name="Faculdade de Ciências", code="FCT")
    page = manager_client.get(reverse("academic:faculty_list")).content.decode()
    assert "FCT" in page and "Faculdade de Ciências" in page


def test_creating_an_academic_year_shows_its_label(manager_client):
    """Year 2030 is listed as 2030-2031 and its creation is audited."""
    manager_client.post(reverse("academic:academicyear_create"), {"start_year": 2030})
    assert AuditEntry.objects.get().action == "create"
    assert "2030-2031" in manager_client.get(reverse("academic:academicyear_list")).content.decode()


def test_a_duplicate_academic_year_is_a_form_error(manager_client):
    """There is one academic year per start year."""
    AcademicYear.objects.create(start_year=2030)
    response = manager_client.post(reverse("academic:academicyear_create"), {"start_year": 2030})
    assert "start_year" in response.context["form"].errors
    assert AcademicYear.objects.count() == 1


def test_deleting_an_academic_year_in_use_shows_a_message(manager_client):
    """A year used by a study plan is kept."""
    faculty = Faculty.objects.create(name="F", code="F")
    year = AcademicYear.objects.create(start_year=2026)
    StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="C", level="bachelor"),
        academic_year=year,
    )
    response = manager_client.post(
        reverse("academic:academicyear_delete", kwargs={"pk": year.pk}),
        {"reason": "Teste"},
        follow=True,
    )
    assert AcademicYear.objects.filter(pk=year.pk).exists()
    assert "em uso" in response.content.decode()


def test_menu_shows_the_new_links_to_the_manager(manager_client):
    """Faculties and academic years appear in the manager's menu."""
    page = manager_client.get("/").content.decode()
    assert reverse("academic:faculty_list") in page
    assert reverse("academic:academicyear_list") in page
