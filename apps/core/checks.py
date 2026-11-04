"""System checks for the authentication configuration (run by manage.py at startup).

Implements: docs/especificacao/07_arquitetura.md – Authentication. See D41.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, register
from django.core.exceptions import ImproperlyConfigured

from .identity import LOCAL_PROVIDER, get_identity_provider, local_login_allowed


@register()
def check_identity_provider(app_configs, **kwargs) -> list[Error]:
    """Fail startup if the identity provider is unknown or local login is used in production.

    Args:
        app_configs: apps to check (unused; the check is global).

    Returns:
        A list of errors: ``core.E001`` unknown provider, ``core.E002`` local login with
        DEBUG off and ALLOW_LOCAL_LOGIN off.
    """
    try:
        get_identity_provider()
    except ImproperlyConfigured as exc:
        return [Error(str(exc), id="core.E001", hint="Check AUTH_IDENTITY_PROVIDER.")]
    path = getattr(settings, "AUTH_IDENTITY_PROVIDER", LOCAL_PROVIDER)
    if path == LOCAL_PROVIDER and not local_login_allowed():
        return [
            Error(
                "Local password login is configured in production.",
                id="core.E002",
                hint="Configure the institutional provider, or set ALLOW_LOCAL_LOGIN=1 "
                "deliberately.",
            )
        ]
    return []
