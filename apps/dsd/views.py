"""Screens of the DSD: list, create, state grid, state change and offerings (T2.1-T2.3).

Implements: docs/backlog_fase2.md T2.1 and T2.2; D43 (only the manager creates and changes
the state; the coordinator reads), D86.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, FormView, TemplateView

from apps.academic.models import ClassType, Coordination
from apps.academic.services import class_group_sizes
from apps.core.generic import (
    ManagedCreateView,
    ManagedListView,
    ManagedViewMixin,
    PageMixin,
    add_validation_errors,
)
from apps.core.permissions import registry

from .forms import (
    DsdForm,
    GenerateOfferingsForm,
    GroupCountForm,
    LeadTeacherForm,
    StateChangeForm,
)
from .lifecycle import cell_writable
from .models import (
    CoordinationSemester,
    Dsd,
    Offering,
    OfferingClassGroup,
    SubGroup,
    TeachingUnit,
)
from .services import (
    GENERATE,
    LEAD_TEACHER,
    TEACHING_UNIT_EDIT,
    change_state,
    create_dsd,
    generate_offerings,
    set_group_count,
    set_lead_teacher,
    stale_unit_ids,
    unit_versions,
)


class DsdListView(ManagedListView):
    """List the DSDs; the manager and the coordinator read them."""

    model = Dsd
    permission_action = "dsd.view"
    template_name = "dsd/dsd_list.html"
    title = _("DSD")


class DsdCreateView(ManagedCreateView):
    """Create the DSD of an academic year; only the PGC manager."""

    model = Dsd
    form_class = DsdForm
    permission_action = "dsd.create"
    success_url = reverse_lazy("dsd:dsd_list")
    title = _("Novo DSD")

    def save_form(self, form):
        """Create the DSD with its semesters; may raise ``ValidationError`` (shown on the form)."""
        return create_dsd(
            form.cleaned_data["academic_year"], self.request.user, form.cleaned_data["reason"]
        )


class DsdDetailView(ManagedViewMixin, DetailView):
    """The state of each semester for each coordination of a DSD; the coordinator only reads."""

    model = Dsd
    permission_action = "dsd.view"
    template_name = "dsd/dsd_detail.html"

    def get_context_data(self, **kwargs):
        """Build one row per coordination with the state of semester 1 and 2."""
        context = super().get_context_data(**kwargs)
        semesters = list(self.object.semesters.order_by("number"))
        states = {
            (row.dsd_semester_id, row.coordination_id): row.status
            for row in CoordinationSemester.objects.filter(dsd_semester__in=semesters)
        }
        labels = dict(CoordinationSemester.Status.choices)
        rows = [
            (
                coordination,
                [
                    labels.get(states.get((semester.pk, coordination.pk)), _("não aberto"))
                    for semester in semesters
                ],
            )
            for coordination in Coordination.objects.select_related("faculty")
        ]
        context.update({"title": str(self.object), "semesters": semesters, "rows": rows})
        return context


class DsdStateView(ManagedViewMixin, FormView):
    """Open, close or reopen a semester for one coordination or for all (D43, D86)."""

    permission_action = "dsd.semester_state.edit"
    form_class = StateChangeForm
    template_name = "core/form.html"
    title = _("Abrir ou fechar semestre")

    @cached_property
    def dsd(self) -> Dsd:
        """The DSD of the URL; read only after the permission check, so a user without it gets
        403 and never learns whether the DSD exists."""
        return get_object_or_404(Dsd, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        """Cancel goes back to the state grid of the DSD."""
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = reverse("dsd:dsd_detail", args=[self.dsd.pk])
        return context

    def form_valid(self, form):
        """Apply the change to the chosen cells and report what changed and what was skipped."""
        data = form.cleaned_data
        semesters = self.dsd.semesters.all()
        if data["semester"] != "both":
            semesters = semesters.filter(number=int(data["semester"]))
        coordinations = (
            [data["coordination"]] if data["coordination"] else Coordination.objects.all()
        )
        try:
            result = change_state(
                self.request.user, data["action"], semesters, coordinations, data["reason"]
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(
            self.request,
            _("Alterados: %(changed)s. Sem efeito: %(skipped)s.")
            % {"changed": len(result.changed), "skipped": len(result.skipped)},
        )
        return redirect("dsd:dsd_detail", pk=self.dsd.pk)


class OfferingListView(ManagedViewMixin, TemplateView):
    """The offerings of a DSD by semester and coordination, with the turmas and their size.

    The manager and the coordinator read it (``dsd.view``, D69). The size is the number that
    counts for the turma in the academic year (D81), marked provisional while it is an estimate.
    """

    permission_action = "dsd.view"
    template_name = "dsd/offering_list.html"

    def get_context_data(self, **kwargs):
        """Filter by semester and coordination and attach the turmas with their size."""
        context = super().get_context_data(**kwargs)
        dsd = get_object_or_404(Dsd, pk=self.kwargs["pk"])
        offerings = (
            Offering.objects.filter(dsd_semester__dsd=dsd)
            .select_related("dsd_semester", "subject__coordination", "subject__study_plan__course")
            .prefetch_related("class_group_links__class_group", "teaching_units")
        )
        params = self.request.GET
        if params.get("semester") in ("1", "2"):
            offerings = offerings.filter(dsd_semester__number=int(params["semester"]))
        if params.get("coordination", "").isdigit():
            offerings = offerings.filter(subject__coordination_id=int(params["coordination"]))
        sizes = class_group_sizes(dsd.academic_year)
        rows = [
            (
                offering,
                [
                    (link.class_group, sizes.get(link.class_group_id))
                    for link in offering.class_group_links.all()
                ],
            )
            for offering in offerings
        ]
        context.update(
            {
                "dsd": dsd,
                "title": _("Ofertas do %(dsd)s") % {"dsd": dsd},
                "rows": rows,
                "can_generate": bool(registry.coordination_ids(self.request.user, GENERATE)),
                "editable_coordinations": registry.coordination_ids(
                    self.request.user, LEAD_TEACHER
                ),
                "coordinations": Coordination.objects.select_related("faculty"),
                "selected_semester": params.get("semester", ""),
                "selected_coordination": params.get("coordination", ""),
            }
        )
        return context


class OfferingGenerateView(PageMixin, LoginRequiredMixin, FormView):
    """Generate the offerings of a DSD; only a manager who covers some coordination (D87)."""

    form_class = GenerateOfferingsForm
    template_name = "core/form.html"
    title = _("Gerar ofertas")

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who cover no coordination for the action before any handler runs."""
        if request.user.is_authenticated and not registry.coordination_ids(request.user, GENERATE):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def dsd(self) -> Dsd:
        """The DSD of the URL; read after the permission check (403, never 404)."""
        return get_object_or_404(Dsd, pk=self.kwargs["pk"])

    def get_form_kwargs(self):
        """Offer only the coordinations the manager covers."""
        kwargs = super().get_form_kwargs()
        kwargs["coordination_ids"] = registry.coordination_ids(self.request.user, GENERATE)
        return kwargs

    def get_context_data(self, **kwargs):
        """Cancel goes back to the offerings of the DSD."""
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = reverse("dsd:offering_list", args=[self.dsd.pk])
        return context

    def form_valid(self, form):
        """Generate and report what was created, what is stale and what was skipped."""
        data = form.cleaned_data
        semesters = self.dsd.semesters.all()
        if data["semester"] != "both":
            semesters = semesters.filter(number=int(data["semester"]))
        only = [data["coordination"].pk] if data["coordination"] else None
        result = generate_offerings(self.request.user, semesters, only, data["reason"])
        messages.success(
            self.request,
            _(
                "Ofertas criadas: %(offerings)s; turmas ligadas: %(links)s; "
                "unidades letivas: %(units)s. "
                "Fechadas: %(blocked)s; fora do âmbito: %(scope)s; obsoletas: %(stale)s."
            )
            % {
                "offerings": result.created_offerings,
                "links": result.created_links,
                "units": result.created_units,
                "blocked": len(result.blocked),
                "scope": len(result.out_of_scope),
                "stale": result.stale_offerings + result.stale_links + result.stale_units,
            },
        )
        return redirect("dsd:offering_list", pk=self.dsd.pk)


class OfferingLeadTeacherView(PageMixin, LoginRequiredMixin, FormView):
    """Set the regente of an offering; the coordinator of its coordination or the manager."""

    form_class = LeadTeacherForm
    template_name = "core/form.html"
    title = _("Definir regente")

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who cover no coordination, then those who do not cover this one."""
        if request.user.is_authenticated:
            if not registry.coordination_ids(request.user, LEAD_TEACHER):
                raise PermissionDenied
            registry.require_on_coordination(
                request.user, LEAD_TEACHER, self.offering.subject.coordination_id
            )
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def offering(self) -> Offering:
        """The offering of the URL, read only after the first permission check."""
        return get_object_or_404(
            Offering.objects.select_related("subject", "dsd_semester__dsd__academic_year"),
            pk=self.kwargs["pk"],
        )

    def get_form_kwargs(self):
        """Give the form the offering."""
        kwargs = super().get_form_kwargs()
        kwargs["offering"] = self.offering
        return kwargs

    def get_context_data(self, **kwargs):
        """Cancel goes back to the offerings of the DSD."""
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = reverse(
            "dsd:offering_list", args=[self.offering.dsd_semester.dsd_id]
        )
        return context

    def form_valid(self, form):
        """Save the regente with the version the user saw, or show the error."""
        data = form.cleaned_data
        offering = self.offering
        offering.version = data["version"]  # the copy the user saw: stale ones are refused
        try:
            set_lead_teacher(self.request.user, offering, data["teacher"], data["reason"])
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Regente guardado."))
        return redirect("dsd:offering_list", pk=offering.dsd_semester.dsd_id)


class OfferingDetailView(ManagedViewMixin, TemplateView):
    """An offering with its teaching units, read-only (T3.1b, D89).

    The manager and the coordinator read it (``dsd.view``, D69). Each unit shows its class type,
    the weekly hours read from the subject's load, the turmas that attend it with their size
    (provisional while it is an estimate, D81) and a mark when it is stale.
    """

    permission_action = "dsd.view"
    template_name = "dsd/offering_detail.html"

    def get_context_data(self, **kwargs):
        """Build one row per unit with its hours, turmas, size and stale mark."""
        context = super().get_context_data(**kwargs)
        offering = get_object_or_404(
            Offering.objects.select_related(
                "subject__coordination",
                "subject__study_plan__course",
                "dsd_semester__dsd__academic_year",
                "lead_teacher",
            ),
            pk=self.kwargs["pk"],
        )
        loads = {
            load.class_type_id: load.weekly_hours for load in offering.subject.class_loads.all()
        }
        stale = stale_unit_ids(offering.dsd_semester, offering.subject.coordination_id)
        sizes = class_group_sizes(offering.dsd_semester.dsd.academic_year)
        units = (
            TeachingUnit.objects.filter(offering=offering)
            .select_related("class_type")
            .prefetch_related(
                "members__class_group_link__class_group",
                "members__subgroup__class_group_link__class_group",
            )
        )
        can_edit = cell_writable(
            self.request.user,
            TEACHING_UNIT_EDIT,
            offering.dsd_semester,
            offering.subject.coordination_id,
        )
        rows = []
        for unit in units:
            members = list(unit.members.all())
            has_groups = any(member.subgroup_id for member in members)
            groups = [
                member.subgroup if member.subgroup_id else member.class_group_link.class_group
                for member in members
            ]
            # The size of a group is not stored (D90): only whole turmas have a number.
            counted = (
                [] if has_groups else [sizes[group.pk] for group in groups if group.pk in sizes]
            )
            rows.append(
                {
                    "unit": unit,
                    "weekly_hours": loads.get(unit.class_type_id),
                    "groups": groups,
                    "students": sum(size.students for size in counted) if counted else None,
                    "provisional": any(size.provisional for size in counted),
                    "stale": unit.pk in stale,
                    "has_groups": has_groups,
                    "action": self._action(offering, members, can_edit),
                }
            )
        context.update(
            {
                "offering": offering,
                "title": f"{offering.subject.code} – {offering.subject.name}",
                "rows": rows,
            }
        )
        return context

    @staticmethod
    def _action(offering, members, can_edit):
        """Return the button of a unit row, or ``None``.

        A whole turma that is alone in its unit can be divided; the first group of a divided turma
        carries the button to change the number of groups. Merged units have none (T3.3).
        """
        if not can_edit or len(members) != 1:
            return None
        member = members[0]
        if member.subgroup_id:
            if member.subgroup.number != 1:
                return None
            link, label = member.subgroup.class_group_link, _("Alterar n.º de grupos")
        else:
            link, label = member.class_group_link, _("Dividir em grupos")
        url = reverse("dsd:offering_groups", args=[offering.pk, link.pk, member.class_type_id])
        return {"url": url, "label": label}


class GroupCountView(PageMixin, LoginRequiredMixin, FormView):
    """Divide a turma of an offering into groups for a class type, or change the number (D90).

    The coordinator of the coordination and the manager of its Faculty, with the cell rules of
    D86 enforced by ``set_group_count``. The turma size shown is a guide only (Q6).
    """

    form_class = GroupCountForm
    template_name = "dsd/group_count_form.html"
    title = _("Dividir em grupos")

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who cover no coordination, then those who do not cover this one."""
        if request.user.is_authenticated:
            if not registry.coordination_ids(request.user, TEACHING_UNIT_EDIT):
                raise PermissionDenied
            registry.require_on_coordination(
                request.user, TEACHING_UNIT_EDIT, self.offering.subject.coordination_id
            )
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def offering(self) -> Offering:
        """The offering of the URL, read after the first permission check."""
        return get_object_or_404(
            Offering.objects.select_related(
                "subject", "dsd_semester__dsd__academic_year", "subject__study_plan"
            ),
            pk=self.kwargs["pk"],
        )

    @cached_property
    def link(self) -> OfferingClassGroup:
        """The turma of the offering; it must belong to the offering in the URL."""
        return get_object_or_404(
            OfferingClassGroup.objects.select_related("class_group"),
            pk=self.kwargs["link_pk"],
            offering=self.offering,
        )

    @cached_property
    def class_type(self) -> ClassType:
        """The class type of the URL."""
        return get_object_or_404(ClassType, pk=self.kwargs["type_pk"])

    @cached_property
    def current(self) -> int:
        """The number of groups now: 1 for the whole turma."""
        return (
            SubGroup.objects.filter(class_group_link=self.link, class_type=self.class_type).count()
            or 1
        )

    def get_form_kwargs(self):
        """Require the reason when the turma is already divided; start from what is stored."""
        kwargs = super().get_form_kwargs()
        kwargs["changing"] = self.current > 1
        if "data" not in kwargs:
            seen = ",".join(
                f"{pk}:{version}"
                for pk, version in sorted(unit_versions(self.link, self.class_type).items())
            )
            kwargs["initial"] = {"groups": self.current, "seen": seen}
        return kwargs

    def get_context_data(self, **kwargs):
        """Add the turma, the class type and its size (a guide only), and the way back."""
        context = super().get_context_data(**kwargs)
        sizes = class_group_sizes(self.offering.dsd_semester.dsd.academic_year)
        context.update(
            {
                "offering": self.offering,
                "link": self.link,
                "class_type": self.class_type,
                "size": sizes.get(self.link.class_group_id),
                "cancel_url": reverse("dsd:offering_detail", args=[self.offering.pk]),
            }
        )
        return context

    def form_valid(self, form):
        """Apply the new number of groups, or show the error on the form."""
        data = form.cleaned_data
        try:
            set_group_count(
                self.request.user,
                self.link,
                self.class_type,
                data["groups"],
                data["reason"],
                data["seen"] or None,
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Grupos guardados."))
        return redirect("dsd:offering_detail", pk=self.offering.pk)
