"""App configuration for ``dsd``.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 6 (load calculation and
validations) and the DSD module of docs/especificacao/05_dsd_regras.md.
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DsdConfig(AppConfig):
    """Configuration of the dsd app."""

    name = "apps.dsd"
    label = "dsd"
    verbose_name = _("DSD")
