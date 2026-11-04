"""Tests for users, profiles and scopes.

Implements: docs/especificacao/07_arquitetura.md – Permissions (profile + scope per user).
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.models import Profile, RoleAssignment, ScopeKind

User = get_user_model()


@pytest.fixture
def user(db):
    """A plain user without any role."""
    return User.objects.create_user(username="ana", password="x")


def test_project_uses_the_custom_user_model():
    """AUTH_USER_MODEL points to core.User (must be decided before the first migration)."""
    assert User._meta.label == "core.User"


def test_a_user_can_hold_several_profiles_with_different_scopes(user):
    """One user may be coordinator of one coordination and teacher of their own record."""
    RoleAssignment.objects.create(
        user=user, profile=Profile.COORDINATOR, scope_kind=ScopeKind.COORDINATION, scope_id=1
    )
    RoleAssignment.objects.create(
        user=user, profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER, scope_id=7
    )
    assert user.role_assignments.count() == 2


def test_pgc_manager_can_have_several_faculties(user):
    """The PGC manager acts on every Faculty assigned to them: one assignment per Faculty."""
    for faculty_id in (1, 2):
        RoleAssignment.objects.create(
            user=user,
            profile=Profile.PGC_MANAGER,
            scope_kind=ScopeKind.FACULTY,
            scope_id=faculty_id,
        )
    assert user.role_assignments.filter(profile=Profile.PGC_MANAGER).count() == 2


def test_the_same_profile_and_scope_cannot_be_assigned_twice(user):
    """Duplicate (user, profile, scope) is rejected by the database."""
    kwargs = dict(
        user=user, profile=Profile.EXECUTIVE_BOARD, scope_kind=ScopeKind.FACULTY, scope_id=1
    )
    RoleAssignment.objects.create(**kwargs)
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleAssignment.objects.create(**kwargs)


def test_duplicate_is_rejected_even_when_there_is_no_scope(user):
    """Two unscoped assignments of the same profile are duplicates too (NULL scope ids)."""
    kwargs = dict(user=user, profile=Profile.VIEWER, scope_kind=ScopeKind.NONE, scope_id=None)
    RoleAssignment.objects.create(**kwargs)
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleAssignment.objects.create(**kwargs)


@pytest.mark.parametrize(
    ("profile", "scope_kind"),
    [
        (Profile.COORDINATOR, ScopeKind.FACULTY),
        (Profile.COORDINATOR, ScopeKind.NONE),
        (Profile.EXECUTIVE_BOARD, ScopeKind.COORDINATION),
        (Profile.PGC_MANAGER, ScopeKind.COORDINATION),
        (Profile.TEACHER, ScopeKind.FACULTY),
    ],
)
def test_profile_rejects_a_scope_kind_the_specification_does_not_allow(user, profile, scope_kind):
    """Coordinator acts on a coordination, board and manager on Faculties, teacher on self."""
    assignment = RoleAssignment(user=user, profile=profile, scope_kind=scope_kind, scope_id=1)
    with pytest.raises(ValidationError):
        assignment.full_clean()


@pytest.mark.parametrize(
    ("profile", "scope_kind"),
    [
        (Profile.COORDINATOR, ScopeKind.COORDINATION),
        (Profile.EXECUTIVE_BOARD, ScopeKind.FACULTY),
        (Profile.PGC_MANAGER, ScopeKind.FACULTY),
        (Profile.TEACHER, ScopeKind.TEACHER),
    ],
)
def test_profile_accepts_the_scope_kind_the_specification_defines(user, profile, scope_kind):
    """The scope kind defined by the specification for each profile is valid."""
    assignment = RoleAssignment(user=user, profile=profile, scope_kind=scope_kind, scope_id=1)
    assignment.full_clean()


def test_scope_id_is_required_exactly_when_there_is_a_scope(user):
    """A scoped assignment needs an id; an unscoped one must not have it (DB check)."""
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleAssignment.objects.create(
            user=user, profile=Profile.COORDINATOR, scope_kind=ScopeKind.COORDINATION, scope_id=None
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleAssignment.objects.create(
            user=user, profile=Profile.VIEWER, scope_kind=ScopeKind.NONE, scope_id=5
        )
