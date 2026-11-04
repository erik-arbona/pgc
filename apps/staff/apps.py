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

    def ready(self) -> None:
        """Tell the core how to find the Faculty of a teacher scope (D62)."""
        from apps.core.roles import ScopeKind
        from apps.core.scopes import ScopeNotFound, register_scope

        from .models import Teacher

        def teacher_scope(scope_id: int) -> int:
            faculty_id = (
                Teacher.objects.filter(pk=scope_id)
                .values_list("coordination__faculty_id", flat=True)
                .first()
            )
            if faculty_id is None:
                raise ScopeNotFound(f"Teacher {scope_id} does not exist.")
            return faculty_id

        register_scope(ScopeKind.TEACHER, teacher_scope)
