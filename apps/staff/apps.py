"""App configuration for ``staff``.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 2 (teachers).
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class StaffConfig(AppConfig):
    """Configuration of the teaching staff app."""

    name = "apps.staff"
    label = "staff"
    verbose_name = _("Docentes")
