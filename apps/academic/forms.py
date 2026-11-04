"""Forms of ``academic`` for the PGC manager area.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1, data entered by the
PGC manager. Every form that edits an existing record asks for a reason (D40).
"""

from apps.core.generic import ReasonModelForm

from .models import ClassType


class ClassTypeForm(ReasonModelForm):
    """Create or edit a class type (D45). Unchecking ``is_active`` deactivates it."""

    class Meta:
        model = ClassType
        fields = ["code", "name", "position", "is_active"]
