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

from .forms import AcademicYearForm, ClassTypeForm, FacultyForm
from .models import AcademicYear, ClassType, Faculty


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


class FacultyMixin:
    """Settings shared by the Faculty screens."""

    model = Faculty
    permission_action = "faculty.edit"
    success_url = reverse_lazy("academic:faculty_list")


class FacultyListView(FacultyMixin, ManagedListView):
    """List the Faculties."""

    template_name = "academic/faculty_list.html"
    title = _("Faculdades")


class FacultyCreateView(FacultyMixin, ManagedCreateView):
    """Add a Faculty."""

    form_class = FacultyForm
    title = _("Nova faculdade")


class FacultyUpdateView(FacultyMixin, ManagedUpdateView):
    """Edit a Faculty (needs a reason)."""

    form_class = FacultyForm
    title = _("Editar faculdade")


class FacultyDeleteView(FacultyMixin, ManagedDeleteView):
    """Delete a Faculty that has no coordinations or courses."""

    title = _("Eliminar faculdade")


class AcademicYearMixin:
    """Settings shared by the academic year screens."""

    model = AcademicYear
    permission_action = "academic_year.edit"
    success_url = reverse_lazy("academic:academicyear_list")


class AcademicYearListView(AcademicYearMixin, ManagedListView):
    """List the academic years."""

    template_name = "academic/academicyear_list.html"
    title = _("Anos letivos")


class AcademicYearCreateView(AcademicYearMixin, ManagedCreateView):
    """Add an academic year."""

    form_class = AcademicYearForm
    title = _("Novo ano letivo")


class AcademicYearUpdateView(AcademicYearMixin, ManagedUpdateView):
    """Edit an academic year (needs a reason)."""

    form_class = AcademicYearForm
    title = _("Editar ano letivo")


class AcademicYearDeleteView(AcademicYearMixin, ManagedDeleteView):
    """Delete an academic year that nothing uses."""

    title = _("Eliminar ano letivo")
