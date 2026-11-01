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

        def faculties_in(faculty_ids: set[int]) -> set[int]:
            return set(Faculty.objects.filter(pk__in=faculty_ids).values_list("pk", flat=True))

        def coordinations_in(faculty_ids: set[int]) -> set[int]:
            return set(
                Coordination.objects.filter(faculty_id__in=faculty_ids).values_list("pk", flat=True)
            )

        def faculty_label(scope_id: int) -> str:
            return str(Faculty.objects.filter(pk=scope_id).first() or "—")

        def coordination_label(scope_id: int) -> str:
            return str(Coordination.objects.filter(pk=scope_id).first() or "—")

        def faculty_options(faculty_ids: set[int]) -> list[tuple[int, str]]:
            return [(f.pk, str(f)) for f in Faculty.objects.filter(pk__in=faculty_ids)]

        def coordination_options(faculty_ids: set[int]) -> list[tuple[int, str]]:
            found = Coordination.objects.filter(faculty_id__in=faculty_ids).select_related(
                "faculty"
            )
            return [(c.pk, f"{c.faculty.code} – {c.name}") for c in found]

        register_scope(
            ScopeKind.FACULTY, faculty_scope, faculties_in, faculty_label, faculty_options
        )
        register_scope(
            ScopeKind.COORDINATION,
            coordination_scope,
            coordinations_in,
            coordination_label,
            coordination_options,
        )
