"""Views of ``staff`` for the PGC manager area.

Implements: docs/especificacao/02_perfis_e_dados.md – categories and positions; D50 (UI
pattern), D56. Permissions are checked on the server with the registered actions.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from apps.academic.models import Coordination
from apps.core.accounts import create_account_with_role
from apps.core.forms import AccountCreateForm
from apps.core.generic import (
    ManagedCreateView,
    ManagedDeleteView,
    ManagedListView,
    ManagedUpdateView,
    ScopedCreateView,
    ScopedDeleteView,
    ScopedListView,
    ScopedUpdateView,
    ScopedViewMixin,
    add_validation_errors,
)
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.core.permissions import registry

from .forms import CategoryForm, LoadRangeForm, PositionForm, TeacherForm
from .models import Category, LoadRange, Position, Teacher
from .services import (
    delete_load_range,
    delete_teacher,
    load_ranges_for,
    save_load_range,
    save_teacher_with_positions,
)


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
        # One lookup for the whole page: the range in force today for each teacher (D58).
        teachers = list(context["object_list"])
        ranges = load_ranges_for(teachers)
        # Which teachers have an account, and where the manager can still create one (D62).
        linked = dict(
            RoleAssignment.objects.filter(
                profile=Profile.TEACHER,
                scope_kind=ScopeKind.TEACHER,
                scope_id__in=[t.pk for t in teachers],
            ).values_list("scope_id", "user__username")
        )
        account_faculties = registry.scope_ids(self.request.user, "account.edit", ScopeKind.FACULTY)
        for teacher in teachers:
            teacher.load_range = ranges[teacher.pk]
            teacher.account_username = linked.get(teacher.pk)
            teacher.can_create_account = (
                teacher.account_username is None
                and teacher.coordination.faculty_id in account_faculties
            )
        context["object_list"] = teachers
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


class LoadRangeMixin:
    """Settings shared by the hours range screens (University-wide, PGC manager, D58)."""

    model = LoadRange
    permission_action = "load_range.edit"
    success_url = reverse_lazy("staff:loadrange_list")


class FutureRuleOnlyMixin:
    """Send the user back to the list when the rule has already started (D58).

    A rule in force is never edited or deleted from the screens: it is corrected by adding a
    newer rule. The service enforces the same rule; this only gives a friendlier answer.
    """

    def _blocked(self):
        """Return a redirect with a message if the rule is in force, otherwise ``None``."""
        rule = self.get_object()
        if rule.valid_from <= timezone.localdate():
            messages.error(
                self.request,
                _(
                    "Esta regra já está em vigor e não se altera nem se apaga: "
                    "acrescente uma regra com data posterior."
                ),
            )
            return redirect(str(self.success_url))
        return None

    def get(self, request, *args, **kwargs):
        """Show the page only for a rule that has not started."""
        return self._blocked() or super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Accept the form only for a rule that has not started."""
        return self._blocked() or super().post(request, *args, **kwargs)


class LoadRangeListView(LoadRangeMixin, ManagedListView):
    """List the hours ranges, newest first within each subject, with their status.

    A request made by HTMX (``HX-Request`` header) gets only the results fragment (D50).
    """

    title = _("Intervalos de horas")

    def get_template_names(self) -> list[str]:
        """Return the fragment for HTMX requests and the full page otherwise."""
        if self.request.headers.get("HX-Request"):
            return ["staff/_loadrange_results.html"]
        return ["staff/loadrange_list.html"]

    def get_queryset(self):
        """Apply the ``kind`` filter."""
        queryset = LoadRange.objects.select_related("category", "position")
        kind = self.request.GET.get("kind", "")
        if kind in LoadRange.Kind.values:
            queryset = queryset.filter(kind=kind)
        return queryset

    def get_context_data(self, **kwargs):
        """Mark each rule as in force, superseded or future, and add the filter choices."""
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        in_force: dict[tuple, tuple] = {}
        for rule in LoadRange.objects.filter(valid_from__lte=today).order_by("valid_from"):
            subject = (rule.kind, rule.category_id, rule.position_id, rule.teacher_type)
            in_force[subject] = rule.pk
        for rule in context["object_list"]:
            subject = (rule.kind, rule.category_id, rule.position_id, rule.teacher_type)
            if rule.valid_from > today:
                rule.status, rule.editable = _("Futura"), True
            elif in_force.get(subject) == rule.pk:
                rule.status, rule.editable = _("Em vigor"), False
            else:
                rule.status, rule.editable = _("Substituída"), False
        context["kinds"] = LoadRange.Kind.choices
        context["selected_kind"] = self.request.GET.get("kind", "")
        return context


class LoadRangeSaveMixin:
    """Save through ``services.save_load_range``, which validates and audits (D58)."""

    def save_form(self, form):
        """Save the rule with the service so the messages are in Portuguese."""
        rule = form.save(commit=False)
        save_load_range(rule, self.request.user, form.cleaned_data.get("reason", ""))
        return rule


class LoadRangeCreateView(LoadRangeMixin, LoadRangeSaveMixin, ManagedCreateView):
    """Add a rule; the start date defaults to today."""

    form_class = LoadRangeForm
    title = _("Novo intervalo de horas")


class LoadRangeUpdateView(
    LoadRangeMixin, FutureRuleOnlyMixin, LoadRangeSaveMixin, ManagedUpdateView
):
    """Edit a rule that has not started (needs a reason)."""

    form_class = LoadRangeForm
    title = _("Editar intervalo de horas")


class LoadRangeDeleteView(LoadRangeMixin, FutureRuleOnlyMixin, ManagedDeleteView):
    """Delete a rule that has not started."""

    title = _("Eliminar intervalo de horas")

    def delete_object(self, form) -> None:
        """Delete the rule through the audited service."""
        delete_load_range(self.object, self.request.user, form.cleaned_data["reason"])


class TeacherAccountView(TeacherMixin, ScopedViewMixin, FormView):
    """Create the account of a teacher together with the role that links it to them (D62).

    It needs scope over the teacher's Faculty for both ``teacher.edit`` and ``account.edit``.
    The account and the role are created in one transaction. The interface never sets a
    password: the account is created with an unusable one.
    """

    template_name = "core/form.html"
    form_class = AccountCreateForm
    title = _("Criar conta do docente")

    def _load_teacher(self):
        """Return the teacher, or raise ``PermissionDenied`` if their Faculty is out of reach."""
        teacher = get_object_or_404(
            Teacher.objects.select_related("coordination"), pk=self.kwargs["pk"]
        )
        self.require_scope_of(teacher)
        registry.require(
            self.request.user,
            "account.edit",
            ScopeKind.FACULTY,
            teacher.coordination.faculty_id,
        )
        return teacher

    def _already_linked(self) -> bool:
        """Tell whether the teacher already has an account."""
        return RoleAssignment.objects.filter(
            profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER, scope_id=self.teacher.pk
        ).exists()

    def _guard(self):
        """Load the teacher; return a redirect with a message if they already have an account."""
        self.teacher = self._load_teacher()
        if self._already_linked():
            messages.error(self.request, _("Este docente já tem uma conta."))
            return redirect(str(self.success_url))
        return None

    def get(self, request, *args, **kwargs):
        """Show the form for a teacher without an account."""
        return self._guard() or super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Create the account for a teacher without one."""
        return self._guard() or super().post(request, *args, **kwargs)

    def get_initial(self):
        """Suggest the username and the names from the teacher's identifier and name."""
        first, _sep, rest = self.teacher.name.partition(" ")
        return {
            "username": self.teacher.identifier.lower(),
            "first_name": first,
            "last_name": rest,
        }

    def form_valid(self, form):
        """Create the account and the teacher role together."""
        data = form.cleaned_data
        try:
            user = create_account_with_role(
                self.request.user,
                username=data["username"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                email=data["email"],
                profile=Profile.TEACHER,
                scope_kind=ScopeKind.TEACHER,
                scope_id=self.teacher.pk,
                reason=data.get("reason", ""),
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Conta criada. A conta não tem palavra-passe."))
        return redirect(reverse("core:account_update", kwargs={"pk": user.pk}))
