"""Forms of ``academic`` for the PGC manager area.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1, data entered by the
PGC manager. Every form that edits an existing record asks for a reason (D40).
"""

from decimal import Decimal

from django import forms

from apps.core.generic import ReasonModelForm, ScopedModelForm

from .models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
)


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


class StudyPlanForm(ScopedModelForm):
    """Create or edit a study plan version; the courses offered are the manager's own (D51)."""

    scope_field = "course"
    scope_filter = "faculty_id__in"

    class Meta:
        model = StudyPlan
        fields = ["course", "academic_year"]


class SubjectForm(ScopedModelForm):
    """Create or edit a subject; the plans offered are those of the manager's courses (D51).

    The responsible coordination may belong to any Faculty: the specification sets no
    same-Faculty rule between a course and the coordination that runs its subject (D44).
    The form also has one ``hours_<class type id>`` field per active class type, plus the
    types the subject already uses even if deactivated; blank or zero means no hours (D53).
    """

    scope_field = "study_plan"
    scope_filter = "course__faculty_id__in"

    class Meta:
        model = Subject
        fields = [
            "study_plan",
            "code",
            "name",
            "ects",
            "curricular_year",
            "semester",
            "coordination",
            "semester_hours",
            "programme",
        ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        existing = {}
        if self.instance.pk:
            existing = {load.class_type_id: load for load in self.instance.class_loads.all()}
        class_types = ClassType.objects.filter(is_active=True) | ClassType.objects.filter(
            pk__in=existing
        )
        self.class_type_ids: list[int] = []
        for class_type in class_types.distinct().order_by("position", "code"):
            load = existing.get(class_type.pk)
            self.fields[f"hours_{class_type.pk}"] = forms.DecimalField(
                label=f"{class_type.code} – {class_type.name}",
                required=False,
                min_value=Decimal("0"),
                max_digits=4,
                decimal_places=2,
                initial=load.weekly_hours if load else None,
                help_text="Horas semanais.",
            )
            self.class_type_ids.append(class_type.pk)
        # Keep the reason as the last field.
        self.fields["reason"] = self.fields.pop("reason")

    def class_loads(self) -> dict[int, Decimal | None]:
        """Return the weekly hours entered, keyed by class type id (``None`` if blank)."""
        return {pk: self.cleaned_data.get(f"hours_{pk}") for pk in self.class_type_ids}


class ClassGroupCreateForm(ScopedModelForm):
    """Create a turma; the plan is chosen by the system, not by the user (D48, D49)."""

    scope_field = "course"
    scope_filter = "faculty_id__in"

    class Meta:
        model = ClassGroup
        fields = ["course", "intake_year", "label", "last_academic_year"]


class ClassGroupUpdateForm(ScopedModelForm):
    """Edit the label and the last academic year of a turma.

    The course, the intake year and the plan are fixed. The hidden ``version`` field carries
    the version the user saw, so that a concurrent change is detected (D54).
    """

    class Meta:
        model = ClassGroup
        fields = ["label", "last_academic_year", "version"]
        widgets = {"version": forms.HiddenInput()}
