"""App configuration for ``core``.

Implements: docs/especificacao/07_arquitetura.md – common core (users, profiles, permissions,
audit).
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    """Configuration of the shared core app."""

    name = "apps.core"
    label = "core"
    verbose_name = _("Núcleo")

    def ready(self) -> None:
        """Register the system checks of this app (authentication configuration)."""
        from . import checks  # noqa: F401  (importing registers the checks)
