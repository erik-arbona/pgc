"""Views of ``staff`` for the PGC manager area.

Implements: docs/especificacao/02_perfis_e_dados.md – categories and positions; D50 (UI
pattern), D56. Permissions are checked on the server with the registered actions.
"""

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from apps.core.generic import (
    ManagedCreateView,
    ManagedDeleteView,
    ManagedListView,
    ManagedUpdateView,
)

from .forms import CategoryForm, PositionForm
from .models import Category, Position


class CategoryMixin:
    """Settings shared by the category screens."""

    model = Category
    permission_action = "category.edit"
    success_url = reverse_lazy("staff:category_list")


class CategoryListView(CategoryMixin, ManagedListView):
    """List the category entries, including inactive ones."""

    template_name = "staff/category_list.html"
    title = _("Categorias")


class CategoryCreateView(CategoryMixin, ManagedCreateView):
    """Add a category."""

    form_class = CategoryForm
    title = _("Nova categoria")


class CategoryUpdateView(CategoryMixin, ManagedUpdateView):
    """Edit or deactivate a category (needs a reason)."""

    form_class = CategoryForm
    title = _("Editar categoria")


class CategoryDeleteView(CategoryMixin, ManagedDeleteView):
    """Delete a category that no teacher uses."""

    title = _("Eliminar categoria")


class PositionMixin:
    """Settings shared by the position screens."""

    model = Position
    permission_action = "position.edit"
    success_url = reverse_lazy("staff:position_list")


class PositionListView(PositionMixin, ManagedListView):
    """List the position entries, including inactive ones."""

    template_name = "staff/position_list.html"
    title = _("Cargos")


class PositionCreateView(PositionMixin, ManagedCreateView):
    """Add a position."""

    form_class = PositionForm
    title = _("Novo cargo")


class PositionUpdateView(PositionMixin, ManagedUpdateView):
    """Edit or deactivate a position (needs a reason)."""

    form_class = PositionForm
    title = _("Editar cargo")


class PositionDeleteView(PositionMixin, ManagedDeleteView):
    """Delete a position that no teacher uses."""

    title = _("Eliminar cargo")
