"""App configuration for ``sii``.

Implements: docs/especificacao/07_arquitetura.md – integration with the SII (D66).
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SiiConfig(AppConfig):
    """Configuration of the SII integration app (no models)."""

    name = "apps.sii"
    label = "sii"
    verbose_name = _("Integração com o SII")
