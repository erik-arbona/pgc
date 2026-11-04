"""Views of ``academic`` for the PGC manager area.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1; D45 (class types),
D50 (UI pattern). Permissions are checked on the server with the registered actions.
"""

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from apps.core.generic import (
    ManagedCreateView,
    ManagedDeleteView,
    ManagedListView,
    ManagedUpdateView,
)

from .forms import ClassTypeForm
from .models import ClassType


class ClassTypeMixin:
    """Settings shared by the class type screens."""

    model = ClassType
    permission_action = "class_type.edit"
    success_url = reverse_lazy("academic:classtype_list")


class ClassTypeListView(ClassTypeMixin, ManagedListView):
    """List the class types, including inactive ones."""

    template_name = "academic/classtype_list.html"
    title = _("Tipos de aula")


class ClassTypeCreateView(ClassTypeMixin, ManagedCreateView):
    """Add a class type."""

    form_class = ClassTypeForm
    title = _("Novo tipo de aula")


class ClassTypeUpdateView(ClassTypeMixin, ManagedUpdateView):
    """Edit or deactivate a class type (needs a reason)."""

    form_class = ClassTypeForm
    title = _("Editar tipo de aula")


class ClassTypeDeleteView(ClassTypeMixin, ManagedDeleteView):
    """Delete a class type that no subject uses."""

    title = _("Eliminar tipo de aula")
