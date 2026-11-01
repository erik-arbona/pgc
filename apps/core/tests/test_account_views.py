"""View tests for the account screens (T3.4, part 2).

Implements: docs/especificacao/03_requisitos_funcionais.md – accounts managed by the PGC manager;
D50, D51, D59, D62. A manager sees and manages only accounts inside their Faculties, never their
own account or an administrator, and the screens never ask for or show a password.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import AuditEntry, Profile, ScopeKind
from apps.core.tests.test_accounts import World

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def w():
    """Two Faculties with their coordinations, teachers and two managers."""
    return World()


def coordinator(w, username, coordination):
    """An account with a coordinator role over a coordination."""
    return w.person(username, (Profile.COORDINATOR, ScopeKind.COORDINATION, coordination.pk))


def login(client, user):
    """Log a user in and return the client."""
    client.force_login(user)
    return client


def edit_url(user):
    """URL of the edit screen of an account."""
    return reverse("core:account_update", kwargs={"pk": user.pk})


def test_anonymous_visitors_are_redirected_to_login(client):
    """The list requires a session."""
    response = client.get(reverse("core:account_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403_everywhere(client, make_user, w, profile):
    """Only a PGC manager reaches the account screens."""
    target = coordinator(w, "alvo", w.ca)
    login(client, make_user(profile))
    for name, kwargs in (
        ("account_list", {}),
        ("account_create", {}),
        ("account_update", {"pk": target.pk}),
        ("account_deactivate", {"pk": target.pk}),
        ("account_activate", {"pk": target.pk}),
    ):
        url = reverse(f"core:{name}", kwargs=kwargs)
        assert client.get(url).status_code == 403
        assert client.post(url, {"username": "x", "reason": "x"}).status_code == 403
    target.refresh_from_db()
    assert target.is_active and not AuditEntry.objects.filter(entity="core.user").exists()


def test_a_manager_without_a_faculty_and_a_superuser_get_403(client, w):
    """Without an assigned Faculty there is nothing to manage; the superuser flag gives nothing."""
    login(client, w.person("sem_poder"))
    assert client.get(reverse("core:account_list")).status_code == 403
    login(client, User.objects.create_superuser(username="root", password="x"))
    assert client.get(reverse("core:account_list")).status_code == 403


def test_the_list_shows_the_accounts_of_the_managers_faculties(client, w):
    """Accounts of A and accounts without roles are listed; accounts only in B are not."""
    coordinator(w, "coord_a", w.ca)
    coordinator(w, "coord_b", w.cb)
    w.person("vazia")
    page = login(client, w.manager_a).get(reverse("core:account_list")).content.decode()
    assert "coord_a" in page and "vazia" in page and "coord_b" not in page


def test_the_list_hides_the_manager_themselves_and_the_administrators(client, w):
    """You do not manage yourself, and administrator accounts are out of reach."""
    User.objects.create_superuser(username="admin_django", password="x")
    User.objects.create_user(username="pessoal_staff", is_staff=True)
    page = login(client, w.manager_a).get(reverse("core:account_list")).content.decode()
    # The header shows the logged-in user, so look for table rows.
    assert "<td>admin_django</td>" not in page and "<td>pessoal_staff</td>" not in page
    assert "<td>gestor_a</td>" not in page


def test_an_account_with_a_role_elsewhere_is_listed_but_read_only(client, w):
    """Someone who also works in B appears, but with no edit or deactivate links."""
    both = w.person(
        "em_a_e_b",
        (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk),
        (Profile.COORDINATOR, ScopeKind.COORDINATION, w.cb.pk),
    )
    page = login(client, w.manager_a).get(reverse("core:account_list")).content.decode()
    assert "em_a_e_b" in page and "Só leitura" in page
    assert edit_url(both) not in page


def test_creating_an_account_audits_it_and_leaves_no_usable_password(client, w):
    """The account is created with an unusable password and the manager goes to its page."""
    response = login(client, w.manager_a).post(
        reverse("core:account_create"),
        {"username": "ana", "first_name": "Ana", "last_name": "Silva", "email": "a@x.cv"},
    )
    user = User.objects.get(username="ana")
    assert response.status_code == 302 and response["Location"] == edit_url(user)
    assert not user.has_usable_password()
    entry = AuditEntry.objects.get(entity="core.user", action="create")
    assert entry.actor == w.manager_a and entry.entity_id == str(user.pk)


def test_the_forms_have_no_password_or_privilege_fields(client, w):
    """Only names and e-mail can be entered; nothing about passwords or administrator flags."""
    target = coordinator(w, "alvo", w.ca)
    login(client, w.manager_a)
    for response in (
        client.get(reverse("core:account_create")),
        client.get(edit_url(target)),
    ):
        fields = set(response.context["form"].fields)
        assert not fields & {"password", "password1", "is_superuser", "is_staff", "groups"}


def test_posting_administrator_flags_changes_nothing(client, w):
    """Mass assignment of is_superuser or is_staff is ignored."""
    login(client, w.manager_a).post(
        reverse("core:account_create"),
        {"username": "ana", "is_superuser": "on", "is_staff": "on", "password": "abc12345"},
    )
    user = User.objects.get(username="ana")
    assert not (user.is_superuser or user.is_staff) and not user.has_usable_password()


def test_a_username_already_in_use_is_a_form_error(client, w):
    """The duplicate is shown on the form, ignoring letter case."""
    w.person("Ana")
    response = login(client, w.manager_a).post(reverse("core:account_create"), {"username": "ana"})
    assert response.status_code == 200
    assert "username" in response.context["form"].errors
    assert User.objects.filter(username__iexact="ana").count() == 1


def test_editing_an_account_needs_a_reason_and_keeps_the_username(client, w):
    """The names change with a reason; the username posted is ignored."""
    target = coordinator(w, "alvo", w.ca)
    login(client, w.manager_a)
    data = {"first_name": "Ana", "last_name": "Silva", "email": "a@x.cv", "username": "hack"}
    client.post(edit_url(target), data)
    target.refresh_from_db()
    assert target.first_name == ""
    client.post(edit_url(target), {**data, "reason_choice": "data_update"})
    target.refresh_from_db()
    assert (target.first_name, target.username) == ("Ana", "alvo")
    assert AuditEntry.objects.filter(entity="core.user", action="update").exists()


@pytest.mark.parametrize("target_name", ["so_b", "em_a_e_b", "consulta"])
def test_a_manager_cannot_open_an_account_outside_their_reach(client, w, target_name):
    """403 on every screen for accounts of B, mixed accounts and accounts with no Faculty."""
    targets = {
        "so_b": coordinator(w, "so_b", w.cb),
        "em_a_e_b": w.person(
            "em_a_e_b",
            (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk),
            (Profile.COORDINATOR, ScopeKind.COORDINATION, w.cb.pk),
        ),
        "consulta": w.person("consulta", (Profile.VIEWER, ScopeKind.NONE, None)),
    }
    target = targets[target_name]
    login(client, w.manager_a)
    for name in ("account_update", "account_deactivate", "account_activate"):
        url = reverse(f"core:{name}", kwargs={"pk": target.pk})
        assert client.get(url).status_code == 403
        assert client.post(url, {"first_name": "X", "reason": "x"}).status_code == 403
    target.refresh_from_db()
    assert target.is_active and target.first_name == ""


def test_a_manager_cannot_open_their_own_account_or_an_administrator(client, w):
    """Self and administrators give 403."""
    root = User.objects.create_superuser(username="root", password="x")
    login(client, w.manager_a)
    for target in (w.manager_a, root):
        assert client.get(edit_url(target)).status_code == 403
        url = reverse("core:account_deactivate", kwargs={"pk": target.pk})
        assert client.post(url, {"reason": "x"}).status_code == 403
    root.refresh_from_db()
    assert root.is_active


def test_deactivating_and_reactivating_need_a_reason(client, w):
    """The reason is required; both changes are audited."""
    target = coordinator(w, "alvo", w.ca)
    login(client, w.manager_a)
    off = reverse("core:account_deactivate", kwargs={"pk": target.pk})
    client.post(off, {})
    target.refresh_from_db()
    assert target.is_active
    client.post(off, {"reason": "Saiu da Universidade"})
    target.refresh_from_db()
    assert not target.is_active
    client.post(reverse("core:account_activate", kwargs={"pk": target.pk}), {"reason": "Regressou"})
    target.refresh_from_db()
    assert target.is_active
    assert AuditEntry.objects.filter(entity="core.user", action="update").count() == 2


def test_the_edit_page_shows_the_roles_of_the_account(client, w):
    """The account's roles are listed (they are edited in the next part)."""
    target = coordinator(w, "alvo", w.ca)
    page = login(client, w.manager_a).get(edit_url(target)).content.decode()
    assert "Coordenador" in page and "Coord A" in page


def test_the_menu_shows_the_accounts_link_to_a_manager(client, w):
    """Accounts appear in the manager's menu."""
    assert reverse("core:account_list") in login(client, w.manager_a).get("/").content.decode()
