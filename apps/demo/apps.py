"""App configuration for ``demo``.

Implements: docs/dados_ficticios.md – the command that loads the fictitious data set (D65).
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DemoConfig(AppConfig):
    """Configuration of the fictitious-data app (no models)."""

    name = "apps.demo"
    label = "demo"
    verbose_name = _("Dados fictícios")
