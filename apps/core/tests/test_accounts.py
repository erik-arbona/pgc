"""Tests for the account services, including privilege-escalation attempts.

Implements: docs/especificacao/03_requisitos_funcionais.md – accounts by profile managed by the
PGC manager; D38, D39, D51, D62. A manager acts only on the Faculties assigned to them, can grant
only what the specification gives a scope to, never touches their own account, and no secret ever
reaches the audit log.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.academic.models import Coordination, Faculty
from apps.core.accounts import (
    assign_role,
    can_manage_account,
    create_account,
    revoke_role,
    set_active,
    update_account,
)
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.staff.models import Category, Teacher

pytestmark = pytest.mark.django_db

User = get_user_model()


class World:
    """Two Faculties, each with a coordination and a teacher, and two managers."""

    def __init__(self):
        self.fa = Faculty.objects.create(name="Faculdade A", code="FA")
        self.fb = Faculty.objects.create(name="Faculdade B", code="FB")
        self.ca = Coordination.objects.create(faculty=self.fa, name="Coord A")
        self.cb = Coordination.objects.create(faculty=self.fb, name="Coord B")
        doctor = Category.objects.get(name="Doutor")
        self.ta = Teacher.objects.create(
            identifier="TA",
            name="Docente A",
            coordination=self.ca,
            category=doctor,
            teacher_type=Teacher.Type.FULL_TIME,
        )
        self.tb = Teacher.objects.create(
            identifier="TB",
            name="Docente B",
            coordination=self.cb,
            category=doctor,
            teacher_type=Teacher.Type.FULL_TIME,
        )
        self.manager_a = self.manager("gestor_a", self.fa)
        self.manager_ab = self.manager("gestor_ab", self.fa, self.fb)

    @staticmethod
    def manager(username, *faculties):
        """A PGC manager assigned to the given Faculties."""
        user = User.objects.create_user(username=username, password="x")
        for faculty in faculties:
            RoleAssignment.objects.create(
                user=user,
                profile=Profile.PGC_MANAGER,
                scope_kind=ScopeKind.FACULTY,
                scope_id=faculty.pk,
            )
        return user

    @staticmethod
    def person(username, *roles):
        """A user with roles given as (profile, kind, scope_id)."""
        user = User.objects.create_user(username=username)
        for profile, kind, scope_id in roles:
            RoleAssignment.objects.create(
                user=user, profile=profile, scope_kind=kind, scope_id=scope_id
            )
        return user


@pytest.fixture
def w():
    """The two-Faculty world."""
    return World()


def entries(entity):
    """The audit entries of an entity, oldest first."""
    return list(AuditEntry.objects.filter(entity=entity).order_by("pk"))


# --- creating accounts ------------------------------------------------------------------------


def test_creating_an_account_gives_an_unusable_password_and_is_audited(w):
    """The interface never sets a password (D62); the creation leaves one entry."""
    user = create_account(
        w.manager_a, username="ana", first_name="Ana", last_name="Silva", email="a@x.cv"
    )
    assert not user.has_usable_password()
    assert not (user.is_superuser or user.is_staff)
    entry = entries("core.user")[-1]
    assert (entry.action, entry.entity_id, entry.actor) == ("create", str(user.pk), w.manager_a)


def test_a_username_in_use_is_refused_ignoring_case(w):
    """Usernames are unique whatever the letter case."""
    create_account(w.manager_a, username="Ana", first_name="", last_name="", email="")
    with pytest.raises(ValidationError):
        create_account(w.manager_a, username="ana", first_name="", last_name="", email="")


def test_someone_without_an_assigned_faculty_cannot_create_accounts(w):
    """Only a PGC manager with a Faculty may create accounts."""
    nobody = w.person("sem_poder")
    coordinator = w.person("coord", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk))
    for actor in (nobody, coordinator):
        with pytest.raises(PermissionDenied):
            create_account(actor, username="x", first_name="", last_name="", email="")
    assert not User.objects.filter(username="x").exists()


# --- assigning roles --------------------------------------------------------------------------


def test_a_manager_assigns_a_coordinator_role_in_their_faculty(w):
    """The role is saved and audited."""
    target = w.person("coord")
    role = assign_role(w.manager_a, target, Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk)
    assert role.scope_id == w.ca.pk
    assert entries("core.roleassignment")[-1].action == "create"


@pytest.mark.parametrize(
    ("profile", "kind"),
    [
        (Profile.COORDINATOR, ScopeKind.COORDINATION),
        (Profile.EXECUTIVE_BOARD, ScopeKind.FACULTY),
        (Profile.PGC_MANAGER, ScopeKind.FACULTY),
    ],
)
def test_a_manager_cannot_grant_a_role_over_another_faculty(w, profile, kind):
    """Coordinator, executive board and manager roles of Faculty B are out of reach for A."""
    scope_id = w.cb.pk if kind == ScopeKind.COORDINATION else w.fb.pk
    with pytest.raises(PermissionDenied):
        assign_role(w.manager_a, w.person("alvo"), profile, kind, scope_id)
    assert not RoleAssignment.objects.filter(user__username="alvo").exists()


def test_a_manager_can_grant_the_manager_role_of_a_faculty_they_hold(w):
    """You can grant what you hold, on the scopes you hold (D06 allows several managers)."""
    other = w.person("outro")
    assign_role(w.manager_a, other, Profile.PGC_MANAGER, ScopeKind.FACULTY, w.fa.pk)
    assert RoleAssignment.objects.filter(user=other, profile=Profile.PGC_MANAGER).exists()


def test_a_manager_with_two_faculties_can_grant_in_both(w):
    """Authority is per Faculty."""
    assign_role(w.manager_ab, w.person("c1"), Profile.COORDINATOR, ScopeKind.COORDINATION, w.cb.pk)
    assign_role(w.manager_ab, w.person("c2"), Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk)
    assert RoleAssignment.objects.filter(profile=Profile.COORDINATOR).count() == 2


@pytest.mark.parametrize("profile", [Profile.ACADEMIC_SERVICES, Profile.FACILITIES, Profile.VIEWER])
def test_profiles_without_a_defined_scope_cannot_be_granted_by_a_manager(w, profile):
    """Only the operator command grants them until the scope is decided (D62)."""
    with pytest.raises(PermissionDenied):
        assign_role(w.manager_a, w.person("alvo"), profile, ScopeKind.NONE, None)
    with pytest.raises(PermissionDenied):
        assign_role(w.manager_a, w.person("alvo2"), profile, ScopeKind.FACULTY, w.fa.pk)


def test_a_profile_with_the_wrong_scope_kind_is_refused(w):
    """A coordinator is scoped to a coordination, not to a Faculty."""
    with pytest.raises(ValidationError):
        assign_role(w.manager_a, w.person("alvo"), Profile.COORDINATOR, ScopeKind.FACULTY, w.fa.pk)


@pytest.mark.parametrize("scope_id", [987654, 0, -1])
def test_a_scope_id_that_names_nothing_is_refused(w, scope_id):
    """An invented id is a validation error, never a grant over some other Faculty."""
    with pytest.raises(ValidationError):
        assign_role(
            w.manager_a, w.person("alvo"), Profile.COORDINATOR, ScopeKind.COORDINATION, scope_id
        )
    assert not RoleAssignment.objects.filter(user__username="alvo").exists()


def test_a_manager_cannot_grant_roles_to_themselves(w):
    """No self-escalation: another manager has to do it."""
    with pytest.raises(PermissionDenied):
        assign_role(
            w.manager_ab, w.manager_ab, Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk
        )


def test_the_same_role_twice_is_refused(w):
    """A duplicate is a validation error, not a database error."""
    target = w.person("alvo")
    assign_role(w.manager_a, target, Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk)
    with pytest.raises(ValidationError):
        assign_role(w.manager_a, target, Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk)


def test_a_teacher_role_links_one_account_to_the_teacher_of_the_faculty(w):
    """The teacher role points at the teacher (D38) and needs scope over their Faculty."""
    assign_role(w.manager_a, w.person("ana"), Profile.TEACHER, ScopeKind.TEACHER, w.ta.pk)
    with pytest.raises(PermissionDenied):
        assign_role(w.manager_a, w.person("rui"), Profile.TEACHER, ScopeKind.TEACHER, w.tb.pk)


def test_a_teacher_cannot_have_two_accounts(w):
    """One teacher is one person: a second account for the same teacher is refused."""
    assign_role(w.manager_a, w.person("ana"), Profile.TEACHER, ScopeKind.TEACHER, w.ta.pk)
    with pytest.raises(ValidationError):
        assign_role(w.manager_a, w.person("ana2"), Profile.TEACHER, ScopeKind.TEACHER, w.ta.pk)


def test_assigning_a_role_to_a_superuser_account_is_refused(w):
    """Accounts with Django administrator flags are outside the managers' reach."""
    root = User.objects.create_superuser(username="root", password="x")
    with pytest.raises(PermissionDenied):
        assign_role(w.manager_a, root, Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk)


# --- revoking roles ---------------------------------------------------------------------------


def test_a_manager_revokes_a_role_in_their_faculty_with_a_reason(w):
    """The reason is required and the deletion is audited."""
    target = w.person("coord", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk))
    role = target.role_assignments.get()
    with pytest.raises(ValidationError):
        revoke_role(w.manager_a, role, "")
    revoke_role(w.manager_a, role, "Deixou de coordenar")
    assert not target.role_assignments.exists()
    assert entries("core.roleassignment")[-1].action == "delete"


def test_a_manager_cannot_revoke_a_role_of_another_faculty(w):
    """The role of Faculty B stays."""
    target = w.person("coord_b", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.cb.pk))
    with pytest.raises(PermissionDenied):
        revoke_role(w.manager_a, target.role_assignments.get(), "Tentativa")
    assert target.role_assignments.count() == 1


def test_a_manager_cannot_revoke_a_role_without_scope(w):
    """Roles that have no Faculty (viewer, facilities) are operator-only."""
    target = w.person("consulta", (Profile.VIEWER, ScopeKind.NONE, None))
    with pytest.raises(PermissionDenied):
        revoke_role(w.manager_a, target.role_assignments.get(), "Tentativa")


def test_a_manager_cannot_revoke_their_own_roles(w):
    """No lock-out and no self-edit."""
    with pytest.raises(PermissionDenied):
        revoke_role(w.manager_ab, w.manager_ab.role_assignments.first(), "Tentativa")
    assert w.manager_ab.role_assignments.count() == 2


# --- editing, deactivating and who may be managed ---------------------------------------------


def test_can_manage_account_follows_the_faculties_of_all_the_roles(w):
    """Every role of the target must be inside the manager's Faculties."""
    only_a = w.person("so_a", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk))
    both = w.person(
        "ab",
        (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk),
        (Profile.COORDINATOR, ScopeKind.COORDINATION, w.cb.pk),
    )
    only_b = w.person("so_b", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.cb.pk))
    empty = w.person("vazia")
    unscoped = w.person("consulta", (Profile.VIEWER, ScopeKind.NONE, None))
    assert can_manage_account(w.manager_a, only_a)
    assert not can_manage_account(w.manager_a, both)
    assert not can_manage_account(w.manager_a, only_b)
    assert can_manage_account(w.manager_a, empty)
    assert not can_manage_account(w.manager_a, unscoped)
    assert can_manage_account(w.manager_ab, both)


def test_nobody_manages_themselves_a_superuser_or_a_dangling_scope(w):
    """Self, administrator accounts and roles pointing at nothing are not manageable."""
    root = User.objects.create_superuser(username="root", password="x")
    staff = User.objects.create_user(username="staff", is_staff=True)
    dangling = w.person("solto", (Profile.COORDINATOR, ScopeKind.COORDINATION, 987654))
    assert not can_manage_account(w.manager_a, w.manager_a)
    for target in (root, staff, dangling):
        assert not can_manage_account(w.manager_a, target)


def test_updating_an_account_changes_the_names_and_keeps_the_username(w):
    """The username is the identity link; it never changes."""
    target = w.person("ana")
    update_account(
        w.manager_a, target, first_name="Ana", last_name="Silva", email="a@x.cv", reason="Dados"
    )
    target.refresh_from_db()
    assert (target.username, target.first_name, target.email) == ("ana", "Ana", "a@x.cv")
    entry = entries("core.user")[-1]
    assert entry.action == "update" and entry.reason == "Dados"


def test_updating_an_account_that_has_a_role_elsewhere_is_refused(w):
    """A manager of A cannot rename or deactivate someone who also works in B."""
    both = w.person(
        "ab",
        (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk),
        (Profile.COORDINATOR, ScopeKind.COORDINATION, w.cb.pk),
    )
    with pytest.raises(PermissionDenied):
        update_account(w.manager_a, both, first_name="X", last_name="", email="", reason="x")
    with pytest.raises(PermissionDenied):
        set_active(w.manager_a, both, False, "x")
    both.refresh_from_db()
    assert both.is_active and both.first_name == ""


def test_deactivating_an_account_needs_a_reason_and_is_audited(w):
    """Deactivation is the end of an account; the reason is required."""
    target = w.person("coord", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk))
    with pytest.raises(ValidationError):
        set_active(w.manager_a, target, False, "")
    set_active(w.manager_a, target, False, "Saiu da Universidade")
    target.refresh_from_db()
    assert not target.is_active
    set_active(w.manager_a, target, True, "Regressou")
    target.refresh_from_db()
    assert target.is_active


def test_a_manager_cannot_deactivate_themselves_or_an_administrator(w):
    """No self-lock-out, and the Django administrators are untouchable."""
    root = User.objects.create_superuser(username="root", password="x")
    for target in (w.manager_ab, root):
        with pytest.raises(PermissionDenied):
            set_active(w.manager_a if target is root else w.manager_ab, target, False, "x")
    root.refresh_from_db()
    assert root.is_active


def test_a_deactivated_user_loses_the_session_on_the_next_request(client, w):
    """Deactivation works at once, even for someone who is logged in."""
    target = w.person("coord", (Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk))
    client.force_login(target)
    assert client.get("/").status_code == 200
    set_active(w.manager_a, target, False, "Saiu")
    response = client.get("/")
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_no_account_service_writes_a_password_to_the_audit_log(w):
    """Whatever the account services do, the log never holds a hash."""
    user = create_account(w.manager_a, username="ana", first_name="", last_name="", email="")
    update_account(w.manager_a, user, first_name="Ana", last_name="", email="", reason="Nome")
    assign_role(w.manager_a, user, Profile.COORDINATOR, ScopeKind.COORDINATION, w.ca.pk)
    set_active(w.manager_a, user, False, "Saiu")
    text = " ".join(f"{e.old_value} {e.new_value}" for e in AuditEntry.objects.all())
    assert "pbkdf2_" not in text and "password" not in text
