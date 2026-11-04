"""Tests for the hardening found by the independent security review of T3.4.

Implements: D62. The review found no way to escalate privileges; these tests pin the robustness
problems it did find: a server error on exotic digits, usernames that skipped Django's validator
and normalisation, a raw database error when two requests race for one teacher, and an operator
command that could link a superuser.
"""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.urls import reverse

from apps.core.accounts import assign_role, create_account
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.core.tests.test_accounts import World

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def w():
    """Two Faculties with coordinations, teachers and two managers."""
    return World()


def new_account(actor, username):
    """Create an account with a username, leaving the other fields empty."""
    return create_account(actor, username=username, first_name="", last_name="", email="")


# --- a scope with exotic digits must not crash the server ------------------------------------


@pytest.mark.parametrize("scope", ["faculty:²", "faculty:³", "faculty:¹²", "faculty:①"])
def test_exotic_digits_in_the_scope_are_a_message_not_a_server_error(client, w, scope):
    """'²'.isdigit() is True but int('²') fails: it must be rejected as malformed (D62)."""
    target = w.person("alvo")
    client.force_login(w.manager_a)
    response = client.post(
        reverse("core:account_role_add", kwargs={"pk": target.pk}),
        {"profile": "pgc_manager", "scope": scope},
    )
    assert response.status_code == 302
    assert not target.role_assignments.exists()


# --- usernames: Django's validator and Unicode normalisation ---------------------------------


@pytest.mark.parametrize("username", ["ana", "a.silva", "ana_silva-2", "joão", "ana@uni.cv"])
def test_ordinary_usernames_are_accepted(w, username):
    """The usual shapes of a username still work."""
    assert new_account(w.manager_a, username).username == username


@pytest.mark.parametrize(
    "username",
    ["gestor_a​", "gestor a", "<b>x</b>", "a/b", "ana;drop"],
)
def test_usernames_with_invalid_characters_are_refused(w, username):
    """Zero-width characters, spaces, markup and punctuation are rejected."""
    with pytest.raises(ValidationError) as error:
        new_account(w.manager_a, username)
    assert "username" in error.value.message_dict
    assert User.objects.count() == 2  # only the two managers of the scenario


def test_a_lookalike_of_an_existing_username_is_refused(w):
    """Full-width letters normalise to the ASCII ones, so they collide with 'gestor_a'."""
    with pytest.raises(ValidationError):
        new_account(w.manager_a, "ｇestor_a")  # full-width 'g' + 'estor_a'
    assert User.objects.filter(username__iexact="gestor_a").count() == 1


def test_the_stored_username_is_normalised(w):
    """A composed form is stored: 'e' + combining acute becomes the single 'é'."""
    user = new_account(w.manager_a, "josé")
    assert user.username == "josé"


def test_a_username_longer_than_150_characters_is_refused(w):
    """Django's limit is enforced for the audited save too."""
    with pytest.raises(ValidationError):
        new_account(w.manager_a, "a" * 151)


# --- two requests racing for one teacher -----------------------------------------------------


def test_a_database_integrity_error_becomes_a_message(w):
    """If the partial unique constraint fires after the pre-check, the user gets a message."""
    with mock.patch("apps.core.accounts.audited_save", side_effect=IntegrityError("duplicate")):
        with pytest.raises(ValidationError):
            assign_role(w.manager_a, w.person("ana"), Profile.TEACHER, ScopeKind.TEACHER, w.ta.pk)


# --- the operator command ---------------------------------------------------------------------


def test_grant_role_refuses_a_superuser_or_staff_account(w):
    """Administrators are kept apart from business roles (D39, D62)."""
    User.objects.create_superuser(username="root", password="x")
    User.objects.create_user(username="pessoal", is_staff=True)
    for name in ("root", "pessoal"):
        with pytest.raises(CommandError):
            call_command("grant_role", name, "pgc_manager", "faculty", str(w.fa.pk))
    assert not RoleAssignment.objects.filter(user__username__in=["root", "pessoal"]).exists()


def test_grant_role_refuses_a_second_account_for_a_teacher(w):
    """A message instead of a raw IntegrityError."""
    w.person("ana", (Profile.TEACHER, ScopeKind.TEACHER, w.ta.pk))
    w.person("outra")
    with pytest.raises(CommandError):
        call_command("grant_role", "outra", "teacher", "teacher", str(w.ta.pk))
