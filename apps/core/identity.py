"""Identity providers: who the user is (authentication), never what they may do.

Implements: docs/especificacao/07_arquitetura.md – Authentication. The institutional
mechanism (LDAP/Active Directory or SSO) is an open question to confirm with the IT
services, so only the contract and a local provider exist. See D41.

Profiles and scopes always come from ``RoleAssignment``; a provider only identifies.
"""

from __future__ import annotations

from typing import Protocol

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

LOCAL_PROVIDER = "apps.core.identity.LocalIdentityProvider"


class IdentityProvider(Protocol):
    """Contract every identity provider implements (local, LDAP, SSO...)."""

    def authenticate(self, request, **credentials):
        """Return the matching active user, or None if the credentials are not accepted."""
        ...


def local_login_allowed() -> bool:
    """Tell whether local username/password login may be used.

    The specification asks for login with the institutional account, with no new password,
    so local login is for development only: allowed with DEBUG on, or when explicitly
    enabled with ALLOW_LOCAL_LOGIN (D41).

    Returns:
        True if local login is allowed in the current settings.
    """
    return bool(settings.DEBUG or getattr(settings, "ALLOW_LOCAL_LOGIN", False))


class LocalIdentityProvider:
    """Username/password stored in the PGC database (development only, see D41)."""

    def authenticate(self, request, username: str | None = None, password: str | None = None):
        """Check a local username and password.

        Args:
            request: the current request (may be None).
            username: the username entered.
            password: the password entered.

        Returns:
            The active user if the credentials match and local login is allowed, else None.
        """
        if not local_login_allowed():
            return None
        # Reuse Django's checks (password hashing, timing-safe miss, is_active).
        return ModelBackend().authenticate(request, username=username, password=password)


def get_identity_provider() -> IdentityProvider:
    """Instantiate the provider named by ``settings.AUTH_IDENTITY_PROVIDER``.

    Returns:
        The configured provider.

    Raises:
        ImproperlyConfigured: if the dotted path cannot be imported.
    """
    path = getattr(settings, "AUTH_IDENTITY_PROVIDER", LOCAL_PROVIDER)
    try:
        provider_class = import_string(path)
    except ImportError as exc:
        raise ImproperlyConfigured(f"Unknown identity provider: {path}") from exc
    return provider_class()


class IdentityProviderBackend(ModelBackend):
    """Django authentication backend that delegates to the configured identity provider.

    Inherits ``get_user`` from ``ModelBackend`` so sessions keep working; business
    permissions are not Django permissions but ``apps.core.permissions`` (D39).
    """

    def authenticate(self, request, **credentials):
        """Delegate to the configured provider and keep only active users.

        Returns:
            The authenticated user, or None.
        """
        user = get_identity_provider().authenticate(request, **credentials)
        if user is None or not isinstance(user, get_user_model()):
            return None
        return user if self.user_can_authenticate(user) else None
