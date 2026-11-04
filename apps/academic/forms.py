"""Forms of ``academic`` for the PGC manager area.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1, data entered by the
PGC manager. Every form that edits an existing record asks for a reason (D40).
"""

from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.generic import ReasonModelForm, ScopedModelForm

from .messages import GROUP_ERROR_TEXT
from .models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Course,
    CrossCourseSubject,
    Faculty,
    StudyPlan,
    Subject,
    Track,
)
from .services import evaluate_selection


class ClassTypeForm(ReasonModelForm):
    """Create or edit a class type (D45). Unchecking ``is_active`` deactivates it.

    ``preparation_weight`` says how much each weekly hour of this type adds to the preparation
    hours (D61); it is never negative.
    """

    preparation_weight = forms.DecimalField(
        label=_("Peso na preparação"),
        min_value=Decimal("0"),
        max_digits=4,
        decimal_places=2,
        help_text=_(
            "Horas de preparação por cada hora semanal deste tipo; 0 não conta. "
            "Um tipo novo começa em 0."
        ),
    )

    class Meta:
        model = ClassType
        fields = ["code", "name", "position", "is_active", "preparation_weight"]


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
    """Create or edit a course; the Faculty choices are the manager's own (D51).

    The responsible coordination is offered only from the manager's Faculties; the
    same-Faculty rule is enforced by ``Course.clean`` (D67).
    """

    class Meta:
        model = Course
        fields = ["faculty", "name", "level", "responsible_coordination", "sii_ref"]

    def __init__(self, *args, allowed_scope_ids=None, **kwargs) -> None:
        super().__init__(*args, allowed_scope_ids=allowed_scope_ids, **kwargs)
        if allowed_scope_ids is not None:
            field = self.fields["responsible_coordination"]
            field.queryset = field.queryset.filter(faculty_id__in=allowed_scope_ids)


class StudyPlanForm(ScopedModelForm):
    """Create or edit a study plan version; the courses offered are the manager's own (D51)."""

    scope_field = "course"
    scope_filter = "faculty_id__in"

    class Meta:
        model = StudyPlan
        fields = ["course", "academic_year"]


class TrackForm(ScopedModelForm):
    """Create or edit a track (percurso) of a plan; the plans offered are the manager's own (D51).

    A track belongs to one plan version and starts in a curricular year (D79).
    """

    scope_field = "study_plan"
    scope_filter = "course__faculty_id__in"

    class Meta:
        model = Track
        fields = ["study_plan", "code", "name", "first_curricular_year", "sii_ref"]


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
            "sii_ref",
            "track",
        ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.allowed_scope_ids is not None:
            tracks = self.fields["track"]
            tracks.queryset = tracks.queryset.filter(
                study_plan__course__faculty_id__in=self.allowed_scope_ids
            )
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
        self.move_reason_last()

    def class_loads(self) -> dict[int, Decimal | None]:
        """Return the weekly hours entered, keyed by class type id (``None`` if blank)."""
        return {pk: self.cleaned_data.get(f"hours_{pk}") for pk in self.class_type_ids}


class ClassGroupCreateForm(ScopedModelForm):
    """Create a turma; the plan is chosen by the system, not by the user (D48, D49)."""

    scope_field = "course"
    scope_filter = "faculty_id__in"

    class Meta:
        model = ClassGroup
        fields = ["course", "intake_year", "label", "last_academic_year", "track"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.allowed_scope_ids is not None:
            tracks = self.fields["track"]
            tracks.queryset = tracks.queryset.filter(
                study_plan__course__faculty_id__in=self.allowed_scope_ids
            )


class ClassGroupUpdateForm(ScopedModelForm):
    """Edit the label and the last academic year of a turma.

    The course, the intake year and the plan are fixed. The hidden ``version`` field carries
    the version the user saw, so that a concurrent change is detected (D54).
    """

    class Meta:
        model = ClassGroup
        fields = ["label", "last_academic_year", "version"]
        widgets = {"version": forms.HiddenInput()}


class SubjectChoiceField(forms.ModelMultipleChoiceField):
    """Multiple choice of subjects labelled with course, code and name."""

    def label_from_instance(self, obj) -> str:
        """Return e.g. ``Curso (Mestrado) · P1 – Introdução (1.º semestre)``."""
        return (
            f"{obj.study_plan.course} · {obj.code} – {obj.name} "
            f"({obj.curricular_year}.º ano, {obj.semester}.º semestre)"
        )


class CrossCourseGroupForm(ReasonModelForm):
    """Create or edit a cross-course group with its members and allowed courses (D55).

    The member choices are the subjects of the manager's Faculties that are not in another
    group; the course choices are the manager's courses. The group is validated with the
    domain rules (at least two courses, allowed courses among the members' courses).
    """

    subjects = SubjectChoiceField(
        queryset=Subject.objects.none(),
        label=_("Disciplinas do grupo"),
        help_text=_("As disciplinas equivalentes, em planos e cursos diferentes."),
    )
    courses = forms.ModelMultipleChoiceField(
        queryset=Course.objects.none(),
        label=_("Cursos em que é transversal"),
        help_text=_("Só se juntam turmas destes cursos."),
    )

    class Meta:
        model = CrossCourseSubject
        fields = ["name", "notes"]

    def __init__(self, *args, allowed_scope_ids=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        allowed = allowed_scope_ids or set()
        in_this_group = Q(pk__in=[])
        if self.instance.pk:
            in_this_group = Q(cross_course_memberships__cross_course_subject=self.instance)
        self.fields["subjects"].queryset = (
            Subject.objects.filter(study_plan__course__faculty_id__in=allowed)
            .filter(Q(cross_course_memberships__isnull=True) | in_this_group)
            .select_related("study_plan__course")
            .distinct()
        )
        self.fields["courses"].queryset = Course.objects.filter(faculty_id__in=allowed)
        if self.instance.pk:
            self.fields["subjects"].initial = [m.subject_id for m in self.instance.members.all()]
            self.fields["courses"].initial = [
                c.course_id for c in self.instance.allowed_courses.all()
            ]
        self.move_reason_last()

    def clean(self):
        """Apply the domain rules to the proposed members and courses."""
        cleaned = super().clean()
        subjects, courses = cleaned.get("subjects"), cleaned.get("courses")
        if subjects is not None and courses is not None:
            errors, _warnings = evaluate_selection(subjects, courses)
            for error in errors:
                self.add_error(None, GROUP_ERROR_TEXT[error])
        return cleaned
