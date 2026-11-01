"""Tests for creating the account of a teacher from the teacher list (T3.4, part 4).

Implements: docs/especificacao/03_requisitos_funcionais.md – accounts by profile; D38 (the account
of a teacher is a role of kind teacher pointing at them), D62. The account and its role are
created together or not at all, and one teacher has at most one account.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.core.accounts import create_account_with_role
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.core.tests.test_accounts import World

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def w():
    """Two Faculties with coordinations, teachers and two managers."""
    return World()


def url(teacher):
    """URL that creates the account of a teacher."""
    return reverse("staff:teacher_account", kwargs={"pk": teacher.pk})


def teacher_role(user, teacher):
    """Create the role that links an account to a teacher."""
    return RoleAssignment.objects.create(
        user=user, profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER, scope_id=teacher.pk
    )


# --- the database constraint ---


def test_the_database_allows_one_teacher_account_per_teacher(w):
    """A second teacher role for the same teacher violates the unique constraint."""
    teacher_role(User.objects.create_user(username="a"), w.ta)
    with pytest.raises(IntegrityError), transaction.atomic():
        teacher_role(User.objects.create_user(username="b"), w.ta)


def test_the_constraint_only_covers_teacher_roles(w):
    """Other roles may share a numeric scope id, and one account may link to two teachers' ids
    only through different teachers."""
    teacher_role(User.objects.create_user(username="a"), w.ta)
    other = User.objects.create_user(username="c")
    RoleAssignment.objects.create(
        user=other,
        profile=Profile.COORDINATOR,
        scope_kind=ScopeKind.COORDINATION,
        scope_id=w.ta.pk,
    )
    teacher_role(User.objects.create_user(username="d"), w.tb)
    assert RoleAssignment.objects.filter(profile=Profile.TEACHER).count() == 2
    assert RoleAssignment.objects.filter(profile=Profile.COORDINATOR).count() == 1


# --- the service ---


def test_the_account_and_its_teacher_role_are_created_together(w):
    """One call creates the user, the role and their audit entries."""
    user = create_account_with_role(
        w.manager_a,
        username="ana",
        first_name="Ana",
        last_name="Silva",
        email="a@x.cv",
        profile=Profile.TEACHER,
        scope_kind=ScopeKind.TEACHER,
        scope_id=w.ta.pk,
    )
    assert not user.has_usable_password()
    assert user.role_assignments.get().scope_id == w.ta.pk
    assert AuditEntry.objects.filter(entity="core.user", action="create").count() == 1
    assert AuditEntry.objects.filter(entity="core.roleassignment", action="create").count() == 1


def test_if_the_role_is_refused_the_account_is_not_created(w):
    """Atomic: a teacher of another Faculty gives 403 and leaves no account behind."""
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        create_account_with_role(
            w.manager_a,
            username="rui",
            first_name="",
            last_name="",
            email="",
            profile=Profile.TEACHER,
            scope_kind=ScopeKind.TEACHER,
            scope_id=w.tb.pk,
        )
    assert not User.objects.filter(username="rui").exists()
    assert not AuditEntry.objects.filter(entity="core.user", action="create").exists()


# --- the screen ---


def test_the_list_offers_to_create_the_account_of_a_teacher_without_one(client, w):
    """'Criar conta' appears for teachers without an account; the username appears for the rest."""
    teacher_role(User.objects.create_user(username="ana_conta"), w.ta)
    client.force_login(w.manager_a)
    other = w.ta.__class__.objects.create(
        identifier="TA2",
        name="Docente Dois",
        coordination=w.ca,
        category=w.ta.category,
        teacher_type=w.ta.teacher_type,
    )
    page = client.get(reverse("staff:teacher_list")).content.decode()
    assert "ana_conta" in page
    assert url(other) in page and url(w.ta) not in page


def test_the_account_column_does_not_add_queries_per_teacher(client, w):
    """Linked accounts of the whole page are found with a fixed number of queries."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    client.force_login(w.manager_a)
    with CaptureQueriesContext(connection) as few:
        client.get(reverse("staff:teacher_list"))
    for i in range(10):
        extra = w.ta.__class__.objects.create(
            identifier=f"X{i}",
            name=f"Docente {i}",
            coordination=w.ca,
            category=w.ta.category,
            teacher_type=w.ta.teacher_type,
        )
        teacher_role(User.objects.create_user(username=f"u{i}"), extra)
    with CaptureQueriesContext(connection) as many:
        client.get(reverse("staff:teacher_list"))
    assert len(many) == len(few)


def test_the_form_starts_with_the_teachers_name_and_identifier(client, w):
    """The username and names are suggested from the teacher."""
    client.force_login(w.manager_a)
    form = client.get(url(w.ta)).context["form"]
    assert form.initial["username"] == "ta"
    assert form.initial["first_name"] == "Docente"
    assert form.initial["last_name"] == "A"


def test_creating_the_account_links_it_to_the_teacher_and_opens_its_page(client, w):
    """The account, the teacher role and the redirect to the account page."""
    client.force_login(w.manager_a)
    response = client.post(
        url(w.ta), {"username": "docente_a", "first_name": "Docente", "last_name": "A", "email": ""}
    )
    user = User.objects.get(username="docente_a")
    assert response.status_code == 302
    assert response["Location"] == reverse("core:account_update", kwargs={"pk": user.pk})
    assert user.role_assignments.get().scope_id == w.ta.pk
    assert not user.has_usable_password() and not (user.is_superuser or user.is_staff)


def test_a_duplicate_username_is_a_form_error_and_creates_nothing(client, w):
    """Atomic: the role is not created either."""
    User.objects.create_user(username="docente_a")
    client.force_login(w.manager_a)
    response = client.post(url(w.ta), {"username": "DOCENTE_A"})
    assert response.status_code == 200
    assert "username" in response.context["form"].errors
    assert not RoleAssignment.objects.filter(profile=Profile.TEACHER).exists()


def test_a_teacher_that_already_has_an_account_cannot_get_another(client, w):
    """The user is sent back to the list with a message."""
    teacher_role(User.objects.create_user(username="ana"), w.ta)
    client.force_login(w.manager_a)
    response = client.post(url(w.ta), {"username": "segunda"}, follow=True)
    assert "já tem uma conta" in response.content.decode()
    assert not User.objects.filter(username="segunda").exists()


def test_a_teacher_of_another_faculty_gives_403(client, w):
    """Forged ids do not work: the teacher's Faculty is checked on the server."""
    client.force_login(w.manager_a)
    assert client.get(url(w.tb)).status_code == 403
    assert client.post(url(w.tb), {"username": "rui"}).status_code == 403
    assert not User.objects.filter(username="rui").exists()


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, w, profile):
    """Only a PGC manager can create accounts."""
    client.force_login(make_user(profile))
    assert client.get(url(w.ta)).status_code == 403
    assert client.post(url(w.ta), {"username": "x"}).status_code == 403
    assert not User.objects.filter(username="x").exists()


def test_anonymous_visitors_are_redirected_to_login(client, w):
    """The screen requires a session."""
    response = client.get(url(w.ta))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_administrator_flags_in_the_post_are_ignored(client, w):
    """No mass assignment of is_superuser, is_staff or a password."""
    client.force_login(w.manager_a)
    client.post(
        url(w.ta),
        {"username": "docente_a", "is_superuser": "on", "is_staff": "on", "password": "abc12345"},
    )
    user = User.objects.get(username="docente_a")
    assert not (user.is_superuser or user.is_staff) and not user.has_usable_password()
