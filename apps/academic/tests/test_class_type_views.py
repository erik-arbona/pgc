"""View tests for the class type screens (first screen of the PGC manager area, T2.6).

Implements: docs/especificacao/07_arquitetura.md – permissions checked on the server and
audit with reason; D40 (reason), D45 (class types), D50 (UI pattern).
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.academic.models import (
    AcademicYear,
    ClassType,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
    SubjectClassLoad,
)
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind

pytestmark = pytest.mark.django_db

User = get_user_model()

SCOPE_FOR = {
    Profile.PGC_MANAGER: ScopeKind.FACULTY,
    Profile.COORDINATOR: ScopeKind.COORDINATION,
    Profile.EXECUTIVE_BOARD: ScopeKind.FACULTY,
    Profile.TEACHER: ScopeKind.TEACHER,
}


def user_with(profile, username="u"):
    """Create a user holding one assignment of the given profile."""
    user = User.objects.create_user(username=username, password="x")
    kind = SCOPE_FOR.get(profile, ScopeKind.NONE)
    RoleAssignment.objects.create(
        user=user, profile=profile, scope_kind=kind, scope_id=None if kind == "none" else 1
    )
    return user


@pytest.fixture
def manager_client(client):
    """A client logged in as a PGC manager."""
    client.force_login(user_with(Profile.PGC_MANAGER, "gestor"))
    return client


def test_anonymous_visitors_are_redirected_to_login(client):
    """The list requires a session."""
    response = client.get(reverse("academic:classtype_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403_on_every_class_type_screen(client, profile):
    """Only the PGC manager reaches the class type screens, on GET and on POST."""
    client.force_login(user_with(profile))
    existing = ClassType.objects.get(code="OUT")
    for name, kwargs in (
        ("classtype_list", {}),
        ("classtype_create", {}),
        ("classtype_update", {"pk": existing.pk}),
        ("classtype_delete", {"pk": existing.pk}),
    ):
        url = reverse(f"academic:{name}", kwargs=kwargs)
        assert client.get(url).status_code == 403
        assert client.post(url, {"code": "X", "name": "X", "reason": "x"}).status_code == 403
    assert ClassType.objects.filter(code="OUT").exists()
    assert not AuditEntry.objects.exists()


def test_a_superuser_without_assignment_gets_403(client):
    """The Django superuser flag gives no business access (D39)."""
    client.force_login(User.objects.create_superuser(username="root", password="x"))
    assert client.get(reverse("academic:classtype_list")).status_code == 403


def test_forbidden_page_is_in_portuguese(client):
    """The 403 page explains the denial in pt-PT."""
    client.force_login(user_with(Profile.VIEWER))
    response = client.get(reverse("academic:classtype_list"))
    assert "Sem permissão" in response.content.decode()


def test_manager_sees_the_initial_class_types(manager_client):
    """The list shows the types loaded by the migration."""
    response = manager_client.get(reverse("academic:classtype_list"))
    assert response.status_code == 200
    assert "Teórica" in response.content.decode()


def test_the_list_is_paginated_by_25(manager_client):
    """More than 25 types spill onto page 2."""
    for i in range(30):
        ClassType.objects.create(code=f"Z{i:02d}", name=f"Extra {i}", position=500 + i)
    first = manager_client.get(reverse("academic:classtype_list"))
    second = manager_client.get(reverse("academic:classtype_list") + "?page=2")
    assert len(first.context["object_list"]) == 25
    assert len(second.context["object_list"]) == 10


def test_creating_a_class_type_writes_one_audit_entry_without_reason(manager_client):
    """Creating needs no reason (D40) and is audited with the actor."""
    response = manager_client.post(
        reverse("academic:classtype_create"),
        {"code": "S", "name": "Seminário", "position": 60, "is_active": "on"},
    )
    assert response.status_code == 302
    created = ClassType.objects.get(code="S")
    entry = AuditEntry.objects.get()
    assert entry.action == "create"
    assert entry.entity_id == str(created.pk)
    assert entry.actor.username == "gestor"


def test_updating_without_a_reason_is_refused(manager_client):
    """An update with a blank reason changes nothing and writes no audit entry."""
    target = ClassType.objects.get(code="OUT")
    response = manager_client.post(
        reverse("academic:classtype_update", kwargs={"pk": target.pk}),
        {"code": "OUT", "name": "Renomeada", "position": 50, "is_active": "on", "reason": ""},
    )
    assert response.status_code == 200
    assert "reason" in response.context["form"].errors
    target.refresh_from_db()
    assert target.name == "Outra"
    assert not AuditEntry.objects.exists()


def test_updating_with_a_reason_is_audited_with_old_and_new_values(manager_client):
    """The audit entry keeps the reason, the previous and the new value."""
    target = ClassType.objects.get(code="OUT")
    manager_client.post(
        reverse("academic:classtype_update", kwargs={"pk": target.pk}),
        {
            "code": "OUT",
            "name": "Outras",
            "position": 50,
            "is_active": "on",
            "reason": "Plural",
        },
    )
    entry = AuditEntry.objects.get()
    assert entry.action == "update"
    assert entry.reason == "Plural"
    assert entry.old_value["name"] == "Outra"
    assert entry.new_value["name"] == "Outras"


def test_deactivating_a_class_type_counts_as_an_update_with_reason(manager_client):
    """Unchecking 'active' needs a reason like any other update."""
    target = ClassType.objects.get(code="OUT")
    data = {"code": "OUT", "name": "Outra", "position": 50, "reason": ""}
    manager_client.post(reverse("academic:classtype_update", kwargs={"pk": target.pk}), data)
    target.refresh_from_db()
    assert target.is_active
    data["reason"] = "Já não se usa"
    manager_client.post(reverse("academic:classtype_update", kwargs={"pk": target.pk}), data)
    target.refresh_from_db()
    assert not target.is_active


def test_deleting_an_unused_class_type_needs_a_reason_and_is_audited(manager_client):
    """The delete page asks for a reason; the deletion is logged."""
    target = ClassType.objects.get(code="OUT")
    url = reverse("academic:classtype_delete", kwargs={"pk": target.pk})
    assert manager_client.get(url).status_code == 200
    manager_client.post(url, {"reason": ""})
    assert ClassType.objects.filter(code="OUT").exists()
    manager_client.post(url, {"reason": "Criado por engano"})
    assert not ClassType.objects.filter(code="OUT").exists()
    entry = AuditEntry.objects.get()
    assert entry.action == "delete"
    assert entry.reason == "Criado por engano"


def test_deleting_a_class_type_in_use_shows_a_message_and_changes_nothing(manager_client):
    """A protected record is kept; the user is told why and nothing is logged."""
    theory = ClassType.objects.get(code="T")
    subject = _subject()
    SubjectClassLoad.objects.create(subject=subject, class_type=theory, weekly_hours=2)
    url = reverse("academic:classtype_delete", kwargs={"pk": theory.pk})
    response = manager_client.post(url, {"reason": "Teste"}, follow=True)
    assert ClassType.objects.filter(code="T").exists()
    assert not AuditEntry.objects.exists()
    assert "em uso" in response.content.decode()


def _subject():
    """Build a minimal subject for the in-use scenario."""
    faculty = Faculty.objects.create(name="FCT", code="FCT")
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="Eng", level="bachelor"),
        academic_year=AcademicYear.objects.create(start_year=2026),
    )
    return Subject.objects.create(
        study_plan=plan,
        code="P1",
        name="Prog",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=Coordination.objects.create(faculty=faculty, name="Inf"),
        semester_hours=Decimal("60"),
    )


def test_home_menu_shows_the_link_only_to_who_may_use_it(client):
    """The menu link is cosmetic but follows the permission."""
    client.force_login(user_with(Profile.PGC_MANAGER, "gestor"))
    assert reverse("academic:classtype_list") in client.get("/").content.decode()
    client.force_login(user_with(Profile.COORDINATOR, "coord"))
    assert reverse("academic:classtype_list") not in client.get("/").content.decode()
