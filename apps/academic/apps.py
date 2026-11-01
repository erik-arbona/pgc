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

    def ready(self) -> None:
        """Tell the core how to find the Faculty of a faculty or coordination scope (D62)."""
        from apps.core.roles import ScopeKind
        from apps.core.scopes import ScopeNotFound, register_scope

        from .models import Coordination, Faculty

        def faculty_scope(scope_id: int) -> int:
            if not Faculty.objects.filter(pk=scope_id).exists():
                raise ScopeNotFound(f"Faculty {scope_id} does not exist.")
            return scope_id

        def coordination_scope(scope_id: int) -> int:
            faculty_id = (
                Coordination.objects.filter(pk=scope_id)
                .values_list("faculty_id", flat=True)
                .first()
            )
            if faculty_id is None:
                raise ScopeNotFound(f"Coordination {scope_id} does not exist.")
            return faculty_id

        register_scope(ScopeKind.FACULTY, faculty_scope)
        register_scope(ScopeKind.COORDINATION, coordination_scope)
