"""Tests for the operator command that grants roles from the command line.

Implements: D62. The command is how the first PGC manager gets in (a Django superuser has no
business access, D39) and the only way to grant the profiles that have no defined scope. It
writes to the audit log with no actor (the system).
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.academic.models import Faculty
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    """An existing user without roles."""
    return get_user_model().objects.create_user(username="ana")


def test_it_grants_the_first_manager_role_over_a_faculty(user):
    """The operator makes the first PGC manager."""
    faculty = Faculty.objects.create(name="FCT", code="FCT")
    call_command("grant_role", "ana", "pgc_manager", "faculty", str(faculty.pk))
    role = RoleAssignment.objects.get(user=user)
    assert (role.profile, role.scope_kind, role.scope_id) == (
        Profile.PGC_MANAGER,
        ScopeKind.FACULTY,
        faculty.pk,
    )
    entry = AuditEntry.objects.get(entity="core.roleassignment")
    assert entry.action == "create" and entry.actor is None


def test_it_grants_a_profile_without_scope_that_managers_cannot_grant(user):
    """Viewer, academic services and facilities are operator-only."""
    call_command("grant_role", "ana", "facilities", "none")
    assert RoleAssignment.objects.get(user=user).profile == Profile.FACILITIES


def test_an_unknown_user_is_an_error():
    """Nothing is created for a user that does not exist."""
    with pytest.raises(CommandError):
        call_command("grant_role", "nao_existe", "viewer", "none")
    assert not RoleAssignment.objects.exists()


def test_a_scope_that_does_not_exist_is_an_error(user):
    """The same check as the interface: the scope id must name a record."""
    with pytest.raises(CommandError):
        call_command("grant_role", "ana", "pgc_manager", "faculty", "987654")
    assert not RoleAssignment.objects.exists()


def test_a_profile_with_the_wrong_scope_kind_is_an_error(user):
    """A manager is scoped to a Faculty."""
    with pytest.raises(CommandError):
        call_command("grant_role", "ana", "pgc_manager", "none")


def test_a_scoped_kind_needs_an_id(user):
    """'faculty' without an id is an error."""
    with pytest.raises(CommandError):
        call_command("grant_role", "ana", "pgc_manager", "faculty")


def test_granting_the_same_role_twice_is_an_error(user):
    """No duplicates."""
    call_command("grant_role", "ana", "viewer", "none")
    with pytest.raises(CommandError):
        call_command("grant_role", "ana", "viewer", "none")
    assert RoleAssignment.objects.count() == 1
