"""App configuration for ``academic``.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1 (academic structure).
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AcademicConfig(AppConfig):
    """Configuration of the academic structure app."""

    name = "apps.academic"
    label = "academic"
    verbose_name = _("Estrutura académica")
