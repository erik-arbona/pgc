"""Shared fixtures for the academic view tests."""

import pytest
from django.contrib.auth import get_user_model

from apps.core.models import Profile, RoleAssignment, ScopeKind

SCOPE_FOR = {
    Profile.PGC_MANAGER: ScopeKind.FACULTY,
    Profile.COORDINATOR: ScopeKind.COORDINATION,
    Profile.EXECUTIVE_BOARD: ScopeKind.FACULTY,
    Profile.TEACHER: ScopeKind.TEACHER,
}


@pytest.fixture
def make_user(db):
    """Return a factory that creates a user holding one assignment of a profile."""

    def factory(profile, username="u"):
        user = get_user_model().objects.create_user(username=username, password="x")
        kind = SCOPE_FOR.get(profile, ScopeKind.NONE)
        RoleAssignment.objects.create(
            user=user, profile=profile, scope_kind=kind, scope_id=None if kind == "none" else 1
        )
        return user

    return factory


@pytest.fixture
def manager_client(client, make_user):
    """A client logged in as a PGC manager named 'gestor'."""
    client.force_login(make_user(Profile.PGC_MANAGER, "gestor"))
    return client
