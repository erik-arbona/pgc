"""View tests for the category and position screens (T3.1, part 2).

Implements: docs/especificacao/02_perfis_e_dados.md – categories and positions entered by the
PGC manager; D40 (reason), D50 (UI pattern), D56.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.academic.models import Coordination, Faculty
from apps.core.models import AuditEntry, Profile
from apps.staff.models import Category, Position, Teacher, TeacherPosition

pytestmark = pytest.mark.django_db

SCREENS = ["category", "position"]
MODELS = {"category": Category, "position": Position}


def new_data(screen):
    """Valid POST data to create an item of the screen."""
    data = {"name": "Novo", "position": 50, "is_active": "on"}
    if screen == "category":
        data["code"] = "NOV"
    return data


def existing(screen):
    """An existing, unused item of the screen's model."""
    if screen == "category":
        return Category.objects.get(name="Mestre")
    return Position.objects.create(name="Assessor")


def edit_data(screen, item, **overrides):
    """POST data that edits an item without changing it, plus overrides."""
    data = {"name": item.name, "position": item.position, "is_active": "on", "reason": "Motivo"}
    if screen == "category":
        data["code"] = item.code
    data.update(overrides)
    return data


@pytest.mark.parametrize("screen", SCREENS)
def test_anonymous_visitors_are_redirected_to_login(client, screen):
    """The lists require a session."""
    response = client.get(reverse(f"staff:{screen}_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, screen, profile):
    """Only the PGC manager reaches these screens, on GET and on POST."""
    client.force_login(make_user(profile))
    item = existing(screen)
    for name, kwargs in (
        ("list", {}),
        ("create", {}),
        ("update", {"pk": item.pk}),
        ("delete", {"pk": item.pk}),
    ):
        url = reverse(f"staff:{screen}_{name}", kwargs=kwargs)
        assert client.get(url).status_code == 403
        assert client.post(url, {**new_data(screen), "reason": "x"}).status_code == 403
    assert not AuditEntry.objects.exists()


@pytest.mark.parametrize("screen", SCREENS)
def test_a_superuser_without_assignment_gets_403(client, screen):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse(f"staff:{screen}_list")).status_code == 403


def test_the_category_list_shows_the_initial_degrees(manager_client):
    """Licenciado, Mestre and Doutor appear after migrating."""
    page = manager_client.get(reverse("staff:category_list")).content.decode()
    assert all(name in page for name in ("Licenciado", "Mestre", "Doutor"))


@pytest.mark.parametrize("screen", SCREENS)
def test_creating_is_audited_without_a_reason(manager_client, screen):
    """A new entry leaves one create entry with the actor."""
    manager_client.post(reverse(f"staff:{screen}_create"), new_data(screen))
    item = MODELS[screen].objects.get(name="Novo")
    entry = AuditEntry.objects.get()
    assert (entry.action, entry.entity_id, entry.actor.username) == (
        "create",
        str(item.pk),
        "gestor",
    )


@pytest.mark.parametrize("screen", SCREENS)
def test_a_duplicate_name_is_a_form_error(manager_client, screen):
    """Names are unique in each catalogue."""
    item = existing(screen)
    response = manager_client.post(
        reverse(f"staff:{screen}_create"), {**new_data(screen), "name": item.name}
    )
    assert response.status_code == 200
    assert "name" in response.context["form"].errors
    assert not AuditEntry.objects.exists()


@pytest.mark.parametrize("screen", SCREENS)
def test_updating_needs_a_reason_and_is_audited(manager_client, screen):
    """No reason: refused. With a reason: renamed, with old and new values logged."""
    item = existing(screen)
    old_name = item.name
    url = reverse(f"staff:{screen}_update", kwargs={"pk": item.pk})
    manager_client.post(url, edit_data(screen, item, name="Renomeado", reason=""))
    item.refresh_from_db()
    assert item.name == old_name and not AuditEntry.objects.exists()
    manager_client.post(url, edit_data(screen, item, name="Renomeado"))
    entry = AuditEntry.objects.get()
    assert (entry.old_value["name"], entry.new_value["name"]) == (old_name, "Renomeado")


@pytest.mark.parametrize("screen", SCREENS)
def test_deactivating_counts_as_an_update_with_reason(manager_client, screen):
    """Unchecking 'active' needs a reason like any other change."""
    item = existing(screen)
    url = reverse(f"staff:{screen}_update", kwargs={"pk": item.pk})
    data = edit_data(screen, item)
    del data["is_active"]
    manager_client.post(url, {**data, "reason": ""})
    item.refresh_from_db()
    assert item.is_active
    manager_client.post(url, data)
    item.refresh_from_db()
    assert not item.is_active


@pytest.mark.parametrize("screen", SCREENS)
def test_deleting_an_unused_entry_is_audited(manager_client, screen):
    """Deletion asks for a reason and is logged."""
    item = existing(screen)
    url = reverse(f"staff:{screen}_delete", kwargs={"pk": item.pk})
    manager_client.post(url, {"reason": ""})
    assert MODELS[screen].objects.filter(pk=item.pk).exists()
    manager_client.post(url, {"reason": "Engano"})
    assert not MODELS[screen].objects.filter(pk=item.pk).exists()
    assert AuditEntry.objects.get().action == "delete"


def _teacher_using(category):
    """Create a full-time teacher with the given category."""
    coordination = Coordination.objects.create(
        faculty=Faculty.objects.create(name="F", code="F"), name="Inf"
    )
    return Teacher.objects.create(
        identifier="D1",
        name="Ana",
        coordination=coordination,
        category=category,
        teacher_type=Teacher.Type.FULL_TIME,
    )


@pytest.mark.parametrize("screen", SCREENS)
def test_deleting_an_entry_in_use_shows_a_message(manager_client, screen):
    """A category or position that a teacher uses is kept; nothing is audited."""
    item = existing(screen)
    if screen == "category":
        _teacher_using(item)
    else:
        teacher = _teacher_using(Category.objects.get(name="Doutor"))
        TeacherPosition.objects.create(teacher=teacher, position=item)
    response = manager_client.post(
        reverse(f"staff:{screen}_delete", kwargs={"pk": item.pk}),
        {"reason": "Teste"},
        follow=True,
    )
    assert MODELS[screen].objects.filter(pk=item.pk).exists()
    assert "em uso" in response.content.decode()
    assert not AuditEntry.objects.exists()


def test_menu_shows_the_catalogue_links_to_the_manager(manager_client):
    """Categories and positions appear in the manager's menu."""
    page = manager_client.get("/").content.decode()
    assert reverse("staff:category_list") in page
    assert reverse("staff:position_list") in page
