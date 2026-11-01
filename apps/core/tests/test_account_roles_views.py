"""View tests for adding and removing the roles of an account (T3.4, part 3).

Implements: docs/especificacao/03_requisitos_funcionais.md – accounts by profile managed by the
PGC manager; D38, D50, D51, D62. The form offers only scopes the manager manages, and every
request is checked again on the server, so a forged profile or scope id gets nowhere.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.core.tests.test_accounts import World

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def w():
    """Two Faculties with coordinations, teachers and two managers."""
    return World()


@pytest.fixture
def target(w):
    """An account with no roles yet."""
    return w.person("alvo")


def add_url(user):
    """URL that adds a role to an account."""
    return reverse("core:account_role_add", kwargs={"pk": user.pk})


def account_url(user):
    """URL of the account page."""
    return reverse("core:account_update", kwargs={"pk": user.pk})


def add(client, user, profile, scope, reason=""):
    """POST a new role."""
    return client.post(add_url(user), {"profile": profile, "scope": scope, "reason": reason})


def roles_of(user):
    """The (profile, kind, scope id) of the account's roles."""
    return set(user.role_assignments.values_list("profile", "scope_kind", "scope_id"))


def test_a_manager_adds_a_coordinator_role_in_their_faculty(client, w, target):
    """The role is created, audited, and the manager returns to the account page."""
    client.force_login(w.manager_a)
    response = add(client, target, "coordinator", f"coordination:{w.ca.pk}")
    assert response.status_code == 302 and response["Location"] == account_url(target)
    assert roles_of(target) == {("coordinator", "coordination", w.ca.pk)}
    entry = AuditEntry.objects.get(entity="core.roleassignment")
    assert entry.action == "create" and entry.actor == w.manager_a


def test_a_manager_adds_the_teacher_role_that_links_an_account_to_a_teacher(client, w, target):
    """The teacher role points at the teacher (D38); a second account is refused."""
    client.force_login(w.manager_a)
    add(client, target, "teacher", f"teacher:{w.ta.pk}")
    assert roles_of(target) == {("teacher", "teacher", w.ta.pk)}
    second = w.person("outra_conta")
    add(client, second, "teacher", f"teacher:{w.ta.pk}")
    assert roles_of(second) == set()


def test_a_manager_can_make_another_manager_of_a_faculty_they_hold(client, w, target):
    """Several managers per Faculty are allowed (D06)."""
    client.force_login(w.manager_a)
    add(client, target, "pgc_manager", f"faculty:{w.fa.pk}")
    assert roles_of(target) == {("pgc_manager", "faculty", w.fa.pk)}


@pytest.mark.parametrize(
    ("profile", "scope"),
    [
        ("coordinator", "coordination:{cb}"),
        ("pgc_manager", "faculty:{fb}"),
        ("executive_board", "faculty:{fb}"),
        ("teacher", "teacher:{tb}"),
    ],
)
def test_a_forged_scope_of_another_faculty_gets_403_and_creates_nothing(
    client, w, target, profile, scope
):
    """Posting an id of Faculty B directly is refused by the server."""
    client.force_login(w.manager_a)
    scope = scope.format(cb=w.cb.pk, fb=w.fb.pk, tb=w.tb.pk)
    assert add(client, target, profile, scope).status_code == 403
    assert roles_of(target) == set()


@pytest.mark.parametrize("profile", ["viewer", "facilities", "academic_services"])
def test_profiles_a_manager_may_not_grant_are_not_accepted(client, w, target, profile):
    """Forging an operator-only profile creates nothing."""
    client.force_login(w.manager_a)
    for scope in (f"faculty:{w.fa.pk}", "none:0"):
        add(client, target, profile, scope)
    assert roles_of(target) == set()


def test_a_profile_with_the_wrong_kind_of_scope_creates_nothing(client, w, target):
    """A coordinator is scoped to a coordination, not a Faculty."""
    client.force_login(w.manager_a)
    add(client, target, "coordinator", f"faculty:{w.fa.pk}")
    assert roles_of(target) == set()


@pytest.mark.parametrize(
    "scope", ["coordination:987654", "coordination:abc", "inventado:1", "x", ""]
)
def test_malformed_or_nonexistent_scopes_create_nothing(client, w, target, scope):
    """Garbage in the scope field is rejected without a server error."""
    client.force_login(w.manager_a)
    response = add(client, target, "coordinator", scope)
    assert response.status_code in (302, 403)
    assert roles_of(target) == set()


def test_the_same_role_twice_is_not_duplicated(client, w, target):
    """The second attempt only shows a message."""
    client.force_login(w.manager_a)
    add(client, target, "coordinator", f"coordination:{w.ca.pk}")
    add(client, target, "coordinator", f"coordination:{w.ca.pk}")
    assert target.role_assignments.count() == 1


def test_only_a_manager_can_reach_the_role_endpoints(client, make_user, w, target):
    """Other profiles get 403 on adding, removing and the scope options."""
    role = RoleAssignment.objects.create(
        user=target,
        profile=Profile.COORDINATOR,
        scope_kind=ScopeKind.COORDINATION,
        scope_id=w.ca.pk,
    )
    for profile in (p for p in Profile if p != Profile.PGC_MANAGER):
        client.force_login(make_user(profile, username=f"u_{profile}"))
        assert add(client, target, "coordinator", f"coordination:{w.ca.pk}").status_code == 403
        remove = reverse("core:account_role_remove", kwargs={"pk": role.pk})
        assert client.get(remove).status_code == 403
        assert client.post(remove, {"reason": "x"}).status_code == 403
        scopes = reverse("core:account_role_scopes", kwargs={"pk": target.pk})
        assert client.get(scopes, {"profile": "coordinator"}).status_code == 403
    assert target.role_assignments.count() == 1


def test_adding_a_role_to_an_account_outside_the_managers_reach_gets_403(client, w):
    """An account that also works in B cannot be changed from A."""
    both = w.person(
        "em_a_e_b",
        (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk),
        (Profile.COORDINATOR, ScopeKind.COORDINATION, w.cb.pk),
    )
    client.force_login(w.manager_a)
    assert add(client, both, "pgc_manager", f"faculty:{w.fa.pk}").status_code == 403
    assert both.role_assignments.count() == 2


def test_a_manager_cannot_add_roles_to_their_own_account(client, w):
    """No self-escalation through the interface either."""
    client.force_login(w.manager_ab)
    assert add(client, w.manager_ab, "coordinator", f"coordination:{w.ca.pk}").status_code == 403
    assert w.manager_ab.role_assignments.count() == 2


def test_the_form_offers_only_the_scopes_of_the_managers_faculties(client, w, target):
    """Faculty B's records are not options; teachers who already have an account are not either."""
    linked = w.person("ana", (Profile.TEACHER, ScopeKind.TEACHER, w.ta.pk))
    assert linked.pk
    client.force_login(w.manager_a)
    form = client.get(account_url(target)).context["role_form"]
    values = {value for value, _ in form.fields["scope"].widget.choices}
    assert f"faculty:{w.fa.pk}" in values and f"coordination:{w.ca.pk}" in values
    assert f"faculty:{w.fb.pk}" not in values and f"coordination:{w.cb.pk}" not in values
    assert f"teacher:{w.tb.pk}" not in values
    assert f"teacher:{w.ta.pk}" not in values  # already linked to the account "ana"


def test_the_profile_choices_are_only_the_grantable_ones(client, w, target):
    """Viewer, facilities and academic services are not in the list."""
    client.force_login(w.manager_a)
    form = client.get(account_url(target)).context["role_form"]
    assert {value for value, _ in form.fields["profile"].choices} == {
        "pgc_manager",
        "coordinator",
        "executive_board",
        "teacher",
    }


def test_the_scope_options_fragment_filters_by_profile(client, w, target):
    """With HTMX, choosing 'coordinator' leaves only coordinations."""
    client.force_login(w.manager_a)
    url = reverse("core:account_role_scopes", kwargs={"pk": target.pk})
    page = client.get(url, {"profile": "coordinator"}, HTTP_HX_REQUEST="true").content.decode()
    assert f"coordination:{w.ca.pk}" in page and "<html" not in page
    assert f"faculty:{w.fa.pk}" not in page and f"coordination:{w.cb.pk}" not in page
    page = client.get(url, {"profile": "pgc_manager"}).content.decode()
    assert f"faculty:{w.fa.pk}" in page and f"coordination:{w.ca.pk}" not in page


def test_removing_a_role_needs_a_reason_and_is_audited(client, w):
    """The confirmation page asks for a reason; the deletion is logged."""
    holder = w.person("coord", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk))
    role = holder.role_assignments.get()
    url = reverse("core:account_role_remove", kwargs={"pk": role.pk})
    client.force_login(w.manager_a)
    assert client.get(url).status_code == 200
    client.post(url, {})
    assert holder.role_assignments.count() == 1
    response = client.post(url, {"reason_choice": "data_update"})
    assert response.status_code == 302 and response["Location"] == account_url(holder)
    assert not holder.role_assignments.exists()
    assert AuditEntry.objects.filter(entity="core.roleassignment", action="delete").exists()


@pytest.mark.parametrize("kind", ["other_faculty", "no_scope", "own_role", "administrator"])
def test_roles_out_of_reach_cannot_be_removed(client, w, kind):
    """Other Faculties, roles without a Faculty, the manager's own roles and administrators."""
    root = User.objects.create_superuser(username="root", password="x")
    roles = {
        "other_faculty": w.person(
            "coord_b", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.cb.pk)
        ).role_assignments.get(),
        "no_scope": w.person(
            "consulta", (Profile.VIEWER, ScopeKind.NONE, None)
        ).role_assignments.get(),
        "own_role": w.manager_a.role_assignments.get(),
        "administrator": RoleAssignment.objects.create(
            user=root,
            profile=Profile.COORDINATOR,
            scope_kind=ScopeKind.COORDINATION,
            scope_id=w.ca.pk,
        ),
    }
    role = roles[kind]
    url = reverse("core:account_role_remove", kwargs={"pk": role.pk})
    client.force_login(w.manager_a)
    assert client.get(url).status_code == 403
    assert client.post(url, {"reason": "Tentativa"}).status_code == 403
    assert RoleAssignment.objects.filter(pk=role.pk).exists()


def test_the_account_page_links_each_role_to_its_removal(client, w):
    """Each role on the page has a remove link."""
    holder = w.person("coord", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk))
    role = holder.role_assignments.get()
    client.force_login(w.manager_a)
    page = client.get(account_url(holder)).content.decode()
    assert reverse("core:account_role_remove", kwargs={"pk": role.pk}) in page
