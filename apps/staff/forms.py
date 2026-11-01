"""Forms of ``staff`` for the PGC manager area.

Implements: docs/especificacao/02_perfis_e_dados.md – categories and positions entered by the
PGC manager. Every form that edits an existing record asks for a reason (D40).
"""

from apps.core.generic import ReasonModelForm

from .models import Category, Position


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
