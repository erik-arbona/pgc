"""Profiles, scope kinds and which scope kind each profile admits.

Implements: docs/especificacao/07_arquitetura.md – Permissions; docs/glossario.md – profile codes.
Pure domain module: no dependency on views, templates or models.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Profile(models.TextChoices):
    """Profiles a user can hold (see docs/especificacao/02_perfis_e_dados.md)."""

    PGC_MANAGER = "pgc_manager", _("Gestor da PGC")
    COORDINATOR = "coordinator", _("Coordenador")
    EXECUTIVE_BOARD = "executive_board", _("Conselho Executivo")
    ACADEMIC_SERVICES = "academic_services", _("Serviços Académicos")
    FACILITIES = "facilities", _("Património")
    VIEWER = "viewer", _("Consulta")
    TEACHER = "teacher", _("Docente")


class ScopeKind(models.TextChoices):
    """What a scope identifier refers to.

    The identifier is stored as a plain number because Faculty, coordination and teacher
    only exist from T2.1/T3.1; a real foreign key replaces it when they do.
    """

    FACULTY = "faculty", _("Faculdade")
    COORDINATION = "coordination", _("Coordenação")
    TEACHER = "teacher", _("Docente")
    NONE = "none", _("Sem âmbito")


# Scope kind that the specification fixes for a profile. Profiles absent from this mapping
# (viewer, academic_services, facilities) have no scope defined in the specification, so any
# kind is accepted until the open point is settled (not invented here).
REQUIRED_SCOPE_KIND: dict[str, str] = {
    Profile.COORDINATOR: ScopeKind.COORDINATION,  # only over their own coordination
    Profile.EXECUTIVE_BOARD: ScopeKind.FACULTY,  # only over their own Faculty
    Profile.PGC_MANAGER: ScopeKind.FACULTY,  # one or several assigned Faculties
    Profile.TEACHER: ScopeKind.TEACHER,  # read-only on their own distribution
}


def scope_kind_allowed(profile: str, scope_kind: str) -> bool:
    """Tell whether a profile admits a scope kind.

    Args:
        profile: a ``Profile`` value.
        scope_kind: a ``ScopeKind`` value.

    Returns:
        True if the specification allows this combination, or does not restrict the profile.
    """
    required = REQUIRED_SCOPE_KIND.get(profile)
    return required is None or required == scope_kind
