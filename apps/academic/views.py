"""Views of ``academic`` for the PGC manager area.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1; D45 (class types),
D50 (UI pattern). Permissions are checked on the server with the registered actions.
"""

from django.db.models import Sum
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

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

from .forms import (
    AcademicYearForm,
    ClassTypeForm,
    CoordinationForm,
    CourseForm,
    FacultyForm,
    StudyPlanForm,
    SubjectForm,
)
from .models import AcademicYear, ClassType, Coordination, Course, Faculty, StudyPlan, Subject
from .services import save_subject_with_loads


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


class CoordinationMixin:
    """Settings shared by the coordination screens (limited to the manager's Faculties, D51)."""

    model = Coordination
    permission_action = "coordination.edit"
    success_url = reverse_lazy("academic:coordination_list")


class CoordinationListView(CoordinationMixin, ScopedListView):
    """List the coordinations of the manager's Faculties."""

    template_name = "academic/coordination_list.html"
    title = _("Coordenações")

    def get_queryset(self):
        """Filter to the manager's Faculties and load the Faculty with each row."""
        return super().get_queryset().select_related("faculty")


class CoordinationCreateView(CoordinationMixin, ScopedCreateView):
    """Add a coordination in one of the manager's Faculties."""

    form_class = CoordinationForm
    title = _("Nova coordenação")


class CoordinationUpdateView(CoordinationMixin, ScopedUpdateView):
    """Edit a coordination (needs a reason)."""

    form_class = CoordinationForm
    title = _("Editar coordenação")


class CoordinationDeleteView(CoordinationMixin, ScopedDeleteView):
    """Delete a coordination that nothing uses."""

    title = _("Eliminar coordenação")


class CourseMixin:
    """Settings shared by the course screens (limited to the manager's Faculties, D51)."""

    model = Course
    permission_action = "course.edit"
    success_url = reverse_lazy("academic:course_list")


class CourseListView(CourseMixin, ScopedListView):
    """List the courses of the manager's Faculties."""

    template_name = "academic/course_list.html"
    title = _("Cursos")

    def get_queryset(self):
        """Filter to the manager's Faculties and load the Faculty with each row."""
        return super().get_queryset().select_related("faculty")


class CourseCreateView(CourseMixin, ScopedCreateView):
    """Add a course in one of the manager's Faculties."""

    form_class = CourseForm
    title = _("Novo curso")


class CourseUpdateView(CourseMixin, ScopedUpdateView):
    """Edit a course (needs a reason)."""

    form_class = CourseForm
    title = _("Editar curso")


class CourseDeleteView(CourseMixin, ScopedDeleteView):
    """Delete a course that nothing uses."""

    title = _("Eliminar curso")


class StudyPlanMixin:
    """Settings shared by the study plan screens (limited to the manager's Faculties, D51)."""

    model = StudyPlan
    permission_action = "study_plan.edit"
    scope_field = "course.faculty_id"
    scope_lookup = "course__faculty__in"
    success_url = reverse_lazy("academic:studyplan_list")


class StudyPlanListView(StudyPlanMixin, ScopedListView):
    """List the plan versions of the manager's courses."""

    template_name = "academic/studyplan_list.html"
    title = _("Planos de estudos")

    def get_queryset(self):
        """Load the course and year with each row."""
        return super().get_queryset().select_related("course", "academic_year")


class StudyPlanCreateView(StudyPlanMixin, ScopedCreateView):
    """Add a plan version to one of the manager's courses."""

    form_class = StudyPlanForm
    title = _("Novo plano de estudos")


class StudyPlanUpdateView(StudyPlanMixin, ScopedUpdateView):
    """Edit a plan version (needs a reason)."""

    form_class = StudyPlanForm
    title = _("Editar plano de estudos")


class StudyPlanDeleteView(StudyPlanMixin, ScopedDeleteView):
    """Delete a plan version that has no subjects or turmas."""

    title = _("Eliminar plano de estudos")


class SubjectMixin:
    """Settings shared by the subject screens (limited to the manager's Faculties, D51)."""

    model = Subject
    permission_action = "subject.edit"
    scope_field = "study_plan.course.faculty_id"
    scope_lookup = "study_plan__course__faculty__in"
    success_url = reverse_lazy("academic:subject_list")


class SubjectListView(SubjectMixin, ScopedListView):
    """List subjects with filters by course and semester.

    A request made by HTMX (``HX-Request`` header) gets only the results fragment; a normal
    request gets the whole page, so the screen also works without JavaScript (D50).
    """

    title = _("Disciplinas")

    def get_template_names(self) -> list[str]:
        """Return the fragment for HTMX requests and the full page otherwise."""
        if self.request.headers.get("HX-Request"):
            return ["academic/_subject_results.html"]
        return ["academic/subject_list.html"]

    def get_queryset(self):
        """Apply the ``course`` and ``semester`` filters; ignore invalid values."""
        queryset = (
            super()
            .get_queryset()
            .select_related("study_plan__course", "coordination")
            .annotate(weekly_total=Sum("class_loads__weekly_hours"))
            .order_by("study_plan__course__name", "curricular_year", "semester", "code")
        )
        course = self.request.GET.get("course", "")
        if course.isdigit():
            queryset = queryset.filter(study_plan__course_id=int(course))
        semester = self.request.GET.get("semester", "")
        if semester in {"1", "2"}:
            queryset = queryset.filter(semester=int(semester))
        return queryset

    def get_context_data(self, **kwargs):
        """Add the courses the manager can filter by and the active filters."""
        context = super().get_context_data(**kwargs)
        context["courses"] = Course.objects.filter(faculty__in=self.allowed_scope_ids())
        context["selected_course"] = self.request.GET.get("course", "")
        context["selected_semester"] = self.request.GET.get("semester", "")
        return context


class SubjectSaveMixin:
    """Save the subject together with its weekly hours per class type (D53)."""

    def save_form(self, form):
        """Save the subject and its hours in one audited transaction.

        The subject itself is written only when it is new or one of its own fields changed.
        """
        instance = form.save(commit=False)
        subject_changed = instance._state.adding or bool(
            set(form.changed_data) & set(form._meta.fields)
        )
        save_subject_with_loads(
            instance,
            form.class_loads(),
            self.request.user,
            form.cleaned_data.get("reason", ""),
            save_subject=subject_changed,
        )
        return instance


class SubjectCreateView(SubjectMixin, SubjectSaveMixin, ScopedCreateView):
    """Add a subject to a plan of the manager's courses."""

    form_class = SubjectForm
    title = _("Nova disciplina")


class SubjectUpdateView(SubjectMixin, SubjectSaveMixin, ScopedUpdateView):
    """Edit a subject (needs a reason)."""

    form_class = SubjectForm
    title = _("Editar disciplina")


class SubjectDeleteView(SubjectMixin, ScopedDeleteView):
    """Delete a subject that has no weekly hours rows or group membership."""

    title = _("Eliminar disciplina")
