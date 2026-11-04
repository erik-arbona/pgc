"""View tests for the coordination and course screens, limited to the manager's Faculties.

Implements: docs/especificacao/07_arquitetura.md – permissions with scope, checked on the
server; D39 (exact scope), D40 (reason), D50 (UI pattern), D51 (manager limited to assigned
Faculties).
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.academic.models import (
    AcademicYear,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
)
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind

pytestmark = pytest.mark.django_db

SCREENS = ["coordination", "course"]
MODELS = {"coordination": Coordination, "course": Course}


def data_for(screen, faculty, name="Novo"):
    """Valid POST data for a screen."""
    data = {"faculty": faculty.pk, "name": name}
    if screen == "course":
        data["level"] = "bachelor"
    return data


def make_item(screen, faculty, name="Existente"):
    """Create an item of the screen's model in a Faculty."""
    if screen == "course":
        return Course.objects.create(faculty=faculty, name=name, level="bachelor")
    return Coordination.objects.create(faculty=faculty, name=name)


@pytest.fixture
def fac_a():
    """Faculty A."""
    return Faculty.objects.create(name="Faculdade A", code="FA")


@pytest.fixture
def fac_b():
    """Faculty B."""
    return Faculty.objects.create(name="Faculdade B", code="FB")


def manager_of(client, *faculties, username="gestor"):
    """Log in a PGC manager assigned to the given Faculties."""
    user = get_user_model().objects.create_user(username=username, password="x")
    for faculty in faculties:
        RoleAssignment.objects.create(
            user=user,
            profile=Profile.PGC_MANAGER,
            scope_kind=ScopeKind.FACULTY,
            scope_id=faculty.pk,
        )
    client.force_login(user)
    return user


@pytest.mark.parametrize("screen", SCREENS)
def test_anonymous_visitors_are_redirected_to_login(client, screen):
    """The lists require a session."""
    response = client.get(reverse(f"academic:{screen}_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, fac_a, screen, profile):
    """Only the PGC manager reaches these screens."""
    client.force_login(make_user(profile))
    for name in ("list", "create"):
        url = reverse(f"academic:{screen}_{name}")
        assert client.get(url).status_code == 403
        assert client.post(url, data_for(screen, fac_a)).status_code == 403
    assert not MODELS[screen].objects.exists()


@pytest.mark.parametrize("screen", SCREENS)
def test_a_manager_with_no_assigned_faculty_gets_403(client, screen):
    """Without any Faculty assignment there is nothing to manage."""
    user = get_user_model().objects.create_user(username="sem", password="x")
    RoleAssignment.objects.create(
        user=user, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.NONE, scope_id=None
    )
    client.force_login(user)
    assert client.get(reverse(f"academic:{screen}_list")).status_code == 403


@pytest.mark.parametrize("screen", SCREENS)
def test_a_superuser_without_assignment_gets_403(client, screen):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse(f"academic:{screen}_list")).status_code == 403


@pytest.mark.parametrize("screen", SCREENS)
def test_the_list_shows_only_the_managers_faculties(client, fac_a, fac_b, screen):
    """A manager of A sees A's items and not B's."""
    make_item(screen, fac_a, "Do A")
    make_item(screen, fac_b, "Do B")
    manager_of(client, fac_a)
    page = client.get(reverse(f"academic:{screen}_list")).content.decode()
    assert "Do A" in page and "Do B" not in page


@pytest.mark.parametrize("screen", SCREENS)
def test_a_manager_of_two_faculties_sees_both(client, fac_a, fac_b, screen):
    """With two assignments the list covers both Faculties."""
    make_item(screen, fac_a, "Do A")
    make_item(screen, fac_b, "Do B")
    manager_of(client, fac_a, fac_b)
    page = client.get(reverse(f"academic:{screen}_list")).content.decode()
    assert "Do A" in page and "Do B" in page


@pytest.mark.parametrize("screen", SCREENS)
def test_a_manager_cannot_touch_another_faculty_object(client, fac_a, fac_b, screen):
    """Editing or deleting an object of B as a manager of A gives 403 and changes nothing."""
    item = make_item(screen, fac_b)
    manager_of(client, fac_a)
    for action in ("update", "delete"):
        url = reverse(f"academic:{screen}_{action}", kwargs={"pk": item.pk})
        assert client.get(url).status_code == 403
        assert (
            client.post(url, {**data_for(screen, fac_b, "Hack"), "reason": "x"}).status_code == 403
        )
    item.refresh_from_db()
    assert item.name == "Existente"
    assert not AuditEntry.objects.exists()


@pytest.mark.parametrize("screen", SCREENS)
def test_creating_in_another_faculty_is_refused(client, fac_a, fac_b, screen):
    """The form only offers the manager's Faculties and the server rejects the rest."""
    manager_of(client, fac_a)
    response = client.post(reverse(f"academic:{screen}_create"), data_for(screen, fac_b))
    assert response.status_code == 200
    assert "faculty" in response.context["form"].errors
    assert not MODELS[screen].objects.exists()
    assert not AuditEntry.objects.exists()


@pytest.mark.parametrize("screen", SCREENS)
def test_creating_in_own_faculty_is_audited(client, fac_a, screen):
    """A valid creation leaves one audit entry with the actor."""
    manager_of(client, fac_a)
    client.post(reverse(f"academic:{screen}_create"), data_for(screen, fac_a))
    item = MODELS[screen].objects.get()
    entry = AuditEntry.objects.get()
    assert (entry.action, entry.entity_id, entry.actor.username) == (
        "create",
        str(item.pk),
        "gestor",
    )


@pytest.mark.parametrize("screen", SCREENS)
def test_updating_needs_a_reason_and_is_audited(client, fac_a, screen):
    """No reason: refused. With a reason: updated with old and new values."""
    item = make_item(screen, fac_a, "Velho")
    manager_of(client, fac_a)
    url = reverse(f"academic:{screen}_update", kwargs={"pk": item.pk})
    client.post(url, {**data_for(screen, fac_a, "Novo"), "reason": ""})
    item.refresh_from_db()
    assert item.name == "Velho" and not AuditEntry.objects.exists()
    client.post(url, {**data_for(screen, fac_a, "Novo"), "reason": "Renomeado"})
    entry = AuditEntry.objects.get()
    assert (entry.old_value["name"], entry.new_value["name"]) == ("Velho", "Novo")
    assert entry.reason == "Renomeado"


@pytest.mark.parametrize("screen", SCREENS)
def test_moving_to_another_faculty_needs_both(client, fac_a, fac_b, screen):
    """A manager of A alone cannot move an item to B; a manager of A and B can."""
    item = make_item(screen, fac_a)
    manager_of(client, fac_a)
    url = reverse(f"academic:{screen}_update", kwargs={"pk": item.pk})
    payload = {**data_for(screen, fac_b, "Existente"), "reason": "Mudança"}
    assert "faculty" in client.post(url, payload).context["form"].errors
    item.refresh_from_db()
    assert item.faculty_id == fac_a.pk

    manager_of(client, fac_a, fac_b, username="gestor2")
    client.post(url, payload)
    item.refresh_from_db()
    assert item.faculty_id == fac_b.pk


@pytest.mark.parametrize("screen", SCREENS)
def test_deleting_an_unused_item_is_audited(client, fac_a, screen):
    """Deletion asks for a reason and is logged."""
    item = make_item(screen, fac_a)
    manager_of(client, fac_a)
    url = reverse(f"academic:{screen}_delete", kwargs={"pk": item.pk})
    client.post(url, {"reason": ""})
    assert MODELS[screen].objects.exists()
    client.post(url, {"reason": "Engano"})
    assert not MODELS[screen].objects.exists()
    assert AuditEntry.objects.get().action == "delete"


def test_deleting_a_course_in_use_shows_a_message(client, fac_a):
    """A course with a study plan is kept."""
    course = make_item("course", fac_a)
    StudyPlan.objects.create(
        course=course, academic_year=AcademicYear.objects.create(start_year=2026)
    )
    manager_of(client, fac_a)
    response = client.post(
        reverse("academic:course_delete", kwargs={"pk": course.pk}),
        {"reason": "Teste"},
        follow=True,
    )
    assert Course.objects.exists()
    assert "em uso" in response.content.decode()
    assert not AuditEntry.objects.exists()


def test_menu_shows_the_links_to_a_manager_with_a_faculty(client, fac_a):
    """Coordinations and courses appear in the menu of a manager with a Faculty."""
    manager_of(client, fac_a)
    page = client.get("/").content.decode()
    assert reverse("academic:coordination_list") in page
    assert reverse("academic:course_list") in page
