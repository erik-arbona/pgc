"""App configuration for ``rooms``.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 8 (rooms).
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class RoomsConfig(AppConfig):
    """Configuration of the rooms app."""

    name = "apps.rooms"
    label = "rooms"
    verbose_name = _("Salas")
