"""Views of ``staff`` for the PGC manager area.

Implements: docs/especificacao/02_perfis_e_dados.md – categories and positions; D50 (UI
pattern), D56. Permissions are checked on the server with the registered actions.
"""

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from apps.academic.models import Coordination
from apps.core.generic import (
    ManagedCreateView,
    ManagedDeleteView,
    ManagedListView,
    ManagedUpdateView,
    ScopedCreateView,
    ScopedDeleteView,
    ScopedListView,
    ScopedUpdateView,
)

from .forms import CategoryForm, PositionForm, TeacherForm
from .models import Category, Position, Teacher
from .services import delete_teacher, save_teacher_with_positions


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


class TeacherMixin:
    """Settings shared by the teacher screens (limited to the manager's Faculties, D51)."""

    model = Teacher
    permission_action = "teacher.edit"
    scope_field = "coordination.faculty_id"
    scope_lookup = "coordination__faculty__in"
    success_url = reverse_lazy("staff:teacher_list")


class TeacherListView(TeacherMixin, ScopedListView):
    """List teachers with filters by coordination, type and activity.

    A request made by HTMX (``HX-Request`` header) gets only the results fragment; a normal
    request gets the whole page, so the screen also works without JavaScript (D50).
    """

    title = _("Docentes")

    def get_template_names(self) -> list[str]:
        """Return the fragment for HTMX requests and the full page otherwise."""
        if self.request.headers.get("HX-Request"):
            return ["staff/_teacher_results.html"]
        return ["staff/teacher_list.html"]

    def get_queryset(self):
        """Apply the ``coordination``, ``teacher_type`` and ``active`` filters."""
        queryset = (
            super()
            .get_queryset()
            .select_related("coordination", "category")
            .order_by("name", "identifier")
        )
        params = self.request.GET
        if params.get("coordination", "").isdigit():
            queryset = queryset.filter(coordination_id=int(params["coordination"]))
        if params.get("teacher_type") in Teacher.Type.values:
            queryset = queryset.filter(teacher_type=params["teacher_type"])
        if params.get("active") in {"0", "1"}:
            queryset = queryset.filter(is_active=params["active"] == "1")
        return queryset

    def get_context_data(self, **kwargs):
        """Add the filter choices and the active filter values."""
        context = super().get_context_data(**kwargs)
        context["coordinations"] = Coordination.objects.filter(faculty__in=self.allowed_scope_ids())
        context["types"] = Teacher.Type.choices
        params = self.request.GET
        context["selected_coordination"] = params.get("coordination", "")
        context["selected_type"] = params.get("teacher_type", "")
        context["selected_active"] = params.get("active", "")
        return context


class TeacherSaveMixin:
    """Save the teacher together with their positions (D56)."""

    def save_form(self, form):
        """Save the teacher and the positions in one audited transaction.

        The teacher itself is written only when it is new or one of its own fields changed.
        """
        teacher = form.save(commit=False)
        teacher_changed = teacher._state.adding or bool(
            set(form.changed_data) & set(form._meta.fields)
        )
        save_teacher_with_positions(
            teacher,
            {p.pk for p in form.cleaned_data["positions"]},
            self.request.user,
            form.cleaned_data.get("reason", ""),
            save_teacher=teacher_changed,
        )
        return teacher


class TeacherCreateView(TeacherMixin, TeacherSaveMixin, ScopedCreateView):
    """Add a teacher to one of the manager's coordinations."""

    form_class = TeacherForm
    title = _("Novo docente")


class TeacherUpdateView(TeacherMixin, TeacherSaveMixin, ScopedUpdateView):
    """Edit a teacher (needs a reason)."""

    form_class = TeacherForm
    title = _("Editar docente")


class TeacherDeleteView(TeacherMixin, ScopedDeleteView):
    """Delete a teacher; their position assignments are deleted with their own audit entries."""

    title = _("Eliminar docente")

    def delete_object(self, form) -> None:
        """Delete the teacher and their positions through the audited service."""
        delete_teacher(self.object, self.request.user, form.cleaned_data["reason"])
