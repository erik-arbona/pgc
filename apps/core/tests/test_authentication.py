"""Tests for local authentication and the identity-provider extension point.

Implements: docs/especificacao/07_arquitetura.md – Authentication (institutional account,
LDAP/AD or SSO to be confirmed: open question). See D41.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from apps.core.checks import check_identity_provider
from apps.core.identity import get_identity_provider
from apps.core.permissions import can

User = get_user_model()


@pytest.fixture
def local_login(settings):
    """Enable the local provider explicitly (pytest-django forces DEBUG off)."""
    settings.AUTH_IDENTITY_PROVIDER = "apps.core.identity.LocalIdentityProvider"
    settings.ALLOW_LOCAL_LOGIN = True
    return settings


@pytest.fixture
def ana(db):
    """An active user with a known password."""
    return User.objects.create_user(username="ana", password="s3cret-pass")


def test_login_with_correct_credentials_starts_a_session(client, local_login, ana):
    """A correct username and password log the user in and redirect."""
    response = client.post(reverse("login"), {"username": "ana", "password": "s3cret-pass"})
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(ana.pk)


def test_login_with_a_wrong_password_is_refused(client, local_login, ana):
    """A wrong password shows the form again and starts no session."""
    response = client.post(reverse("login"), {"username": "ana", "password": "wrong"})
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_inactive_account_cannot_log_in(client, local_login, ana):
    """A deactivated account is refused even with the right password."""
    ana.is_active = False
    ana.save()
    client.post(reverse("login"), {"username": "ana", "password": "s3cret-pass"})
    assert "_auth_user_id" not in client.session


def test_logout_ends_the_session(client, local_login, ana):
    """Logging out (POST) removes the authenticated session."""
    client.force_login(ana)
    response = client.post(reverse("logout"))
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


def test_home_page_requires_login(client, db):
    """Anonymous visitors are sent to the login page."""
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_login_page_is_in_european_portuguese(client, db):
    """The login form is rendered with pt-PT interface text."""
    response = client.get(reverse("login"))
    assert response.status_code == 200
    assert "Entrar" in response.content.decode()


def test_authenticated_user_without_role_assignments_has_no_permissions(local_login, ana):
    """The provider only identifies: profiles and scopes come from RoleAssignment."""
    assert can(ana, "room.edit") is False


def test_unknown_provider_fails_closed_and_is_reported_by_the_system_check(settings, db):
    """A misconfigured provider path refuses logins and fails the startup check."""
    settings.AUTH_IDENTITY_PROVIDER = "apps.core.identity.DoesNotExist"
    with pytest.raises(ImproperlyConfigured):
        get_identity_provider()
    assert [e.id for e in check_identity_provider(None)] == ["core.E001"]


def test_local_login_is_refused_in_production_unless_explicitly_allowed(client, settings, ana):
    """With DEBUG off and ALLOW_LOCAL_LOGIN off, local passwords are not accepted (D41)."""
    settings.AUTH_IDENTITY_PROVIDER = "apps.core.identity.LocalIdentityProvider"
    settings.DEBUG = False
    settings.ALLOW_LOCAL_LOGIN = False

    client.post(reverse("login"), {"username": "ana", "password": "s3cret-pass"})

    assert "_auth_user_id" not in client.session
    assert [e.id for e in check_identity_provider(None)] == ["core.E002"]


def test_local_login_passes_the_check_in_development(settings, db):
    """In development (DEBUG on) the local provider is valid."""
    settings.AUTH_IDENTITY_PROVIDER = "apps.core.identity.LocalIdentityProvider"
    settings.DEBUG = True
    settings.ALLOW_LOCAL_LOGIN = False
    assert check_identity_provider(None) == []
