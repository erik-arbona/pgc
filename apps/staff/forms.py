"""Forms of ``staff`` for the PGC manager area.

Implements: docs/especificacao/02_perfis_e_dados.md – categories and positions entered by the
PGC manager. Every form that edits an existing record asks for a reason (D40).
"""

from apps.core.generic import ReasonModelForm, ScopedModelForm

from .models import Category, Position, Teacher


class CategoryForm(ReasonModelForm):
    """Create or edit a teacher category. Unchecking ``is_active`` deactivates it."""

    class Meta:
        model = Category
        fields = ["code", "name", "position", "is_active"]


class PositionForm(ReasonModelForm):
    """Create or edit a position (cargo). Unchecking ``is_active`` deactivates it."""

    class Meta:
        model = Position
        fields = ["name", "position", "is_active"]


class TeacherForm(ScopedModelForm):
    """Create or edit a teacher; the coordinations offered are in the manager's Faculties (D51).

    Inactive categories are not offered, except the one the teacher already has.
    """

    scope_field = "coordination"
    scope_filter = "faculty_id__in"

    class Meta:
        model = Teacher
        fields = ["identifier", "name", "coordination", "category", "teacher_type", "is_active"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        keep = [self.instance.category_id] if self.instance.pk else []
        categories = self.fields["category"].queryset
        self.fields["category"].queryset = categories.filter(is_active=True) | categories.filter(
            pk__in=keep
        )
