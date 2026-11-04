"""Forms of ``academic`` for the PGC manager area.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1, data entered by the
PGC manager. Every form that edits an existing record asks for a reason (D40).
"""

from apps.core.generic import ReasonModelForm, ScopedModelForm

from .models import AcademicYear, ClassType, Coordination, Course, Faculty


class ClassTypeForm(ReasonModelForm):
    """Create or edit a class type (D45). Unchecking ``is_active`` deactivates it."""

    class Meta:
        model = ClassType
        fields = ["code", "name", "position", "is_active"]


class FacultyForm(ReasonModelForm):
    """Create or edit a Faculty."""

    class Meta:
        model = Faculty
        fields = ["name", "code"]


class AcademicYearForm(ReasonModelForm):
    """Create or edit an academic year (only its start year, D42)."""

    class Meta:
        model = AcademicYear
        fields = ["start_year"]


class CoordinationForm(ScopedModelForm):
    """Create or edit a coordination; the Faculty choices are the manager's own (D51)."""

    class Meta:
        model = Coordination
        fields = ["faculty", "name"]


class CourseForm(ScopedModelForm):
    """Create or edit a course; the Faculty choices are the manager's own (D51)."""

    class Meta:
        model = Course
        fields = ["faculty", "name", "level"]
