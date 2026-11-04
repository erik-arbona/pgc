"""Screens of the DSD: list, create, state grid, state change and offerings (T2.1-T2.3).

Implements: docs/backlog_fase2.md T2.1 and T2.2; D43 (only the manager creates and changes
the state; the coordinator reads), D86.
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, FormView, TemplateView, View

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
from apps.rooms.services import room_summary
from apps.staff.models import Teacher

from .below_minimum import MinimumReasonState
from .coordination_overview import attention_text, coordination_overview
from .forms import (
    ActivityEditForm,
    ActivityForm,
    ActivityRemoveForm,
    DsdForm,
    ExtraAcceptForm,
    GenerateOfferingsForm,
    GroupCountForm,
    LeadTeacherForm,
    MergeForm,
    MinimumReasonForm,
    MinimumReviewForm,
    RoomRequestForm,
    SeparateForm,
    StateChangeForm,
    TeacherAssignForm,
)
from .lifecycle import cell_writable
from .load_facts import (
    load_text,
    minimum_reason_text,
    status_text,
    teacher_loads,
)
from .models import (
    AcceptedExtraHours,
    BelowMinimumReason,
    CoordinationSemester,
    Dsd,
    DsdSemester,
    Offering,
    OfferingClassGroup,
    OtherActivity,
    SubGroup,
    TeachingUnit,
    TeachingUnitMember,
)
from .services import (
    ASSIGNMENT_EDIT,
    GENERATE,
    LEAD_TEACHER,
    REVIEW_MINIMUM,
    TEACHER_SHEET_VIEW,
    TEACHING_UNIT_EDIT,
    add_activity,
    assign_teacher,
    change_state,
    clear_accepted_extra,
    create_dsd,
    edit_activity,
    generate_offerings,
    guest_members,
    merge_load_differences,
    merge_units,
    merged_students,
    partner_offerings,
    remove_activity,
    review_minimum_reason,
    room_request_warnings,
    separate_member,
    set_accepted_extra,
    set_group_count,
    set_lead_teacher,
    set_minimum_reason,
    set_room_request,
    stale_unit_ids,
    unassign_teacher,
    unit_students,
    unit_versions,
)
from .teacher_choices import candidate_teachers, describe_candidates


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
    """An offering with its teaching units, read-only (T3.1b, D89), and the actions on them.

    The manager and the coordinator read it (``dsd.view``, D69). Each unit shows its class type,
    the weekly hours read from the subject's load, the turmas that attend it with their size
    (provisional while it is an estimate, D81), its room request and a mark when it is stale.
    Where the subject is transversal (D92) the page also offers the units of the partner
    offerings to merge with, and lists the turmas of this offering that were merged into another.
    """

    permission_action = "dsd.view"
    template_name = "dsd/offering_detail.html"

    def get_context_data(self, **kwargs):
        """Build the rows of the units, of the partner units and of the merges this was put in."""
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
        coordination_id = offering.subject.coordination_id
        stale = stale_unit_ids(offering.dsd_semester, coordination_id)
        sizes = class_group_sizes(offering.dsd_semester.dsd.academic_year)
        can_edit = cell_writable(
            self.request.user, TEACHING_UNIT_EDIT, offering.dsd_semester, coordination_id
        )
        units = list(self._units(offering))
        rows = self._unit_rows(offering, units, stale, sizes, can_edit)
        partner_rows = []
        guest_rows = []
        if can_edit:
            for partner in partner_offerings(offering):
                partner_rows += [
                    self._row(unit, partner, stale, sizes, can_edit, with_actions=False)
                    for unit in self._units(partner)
                ]
        for member in guest_members(offering):
            host = member.unit.offering
            guest_rows.append(
                {
                    "member": member,
                    "host": host,
                    "label": member.subgroup
                    if member.subgroup_id
                    else member.turma_link.class_group,
                    "separate_url": reverse(
                        "dsd:offering_separate", args=[host.pk, member.unit_id, member.pk]
                    )
                    if can_edit
                    else None,
                }
            )
        context.update(
            {
                "offering": offering,
                "title": f"{offering.subject.code} – {offering.subject.name}",
                "rows": rows,
                "to_assign": sum(1 for row in rows if row["unassigned"]),
                "current_units": sum(1 for row in rows if not row["stale"]),
                "partner_rows": partner_rows,
                "guest_rows": guest_rows,
                "can_edit": can_edit,
            }
        )
        return context

    @cached_property
    def _sheet_coordinations(self) -> set[int]:
        """The coordinations whose teachers' sheets the user may open."""
        return registry.coordination_ids(self.request.user, TEACHER_SHEET_VIEW)

    def _unit_rows(self, offering, units, stale, sizes, can_edit):
        """Build the rows of some units of an offering, with the teacher selector where it applies.

        A current unit without a teacher is marked ``unassigned`` and, to who may write the cell,
        gets the teachers it can be given to, each with the load they would have (T6.2). The
        loads of the teachers of the units and of the candidates are read in one batch.
        """
        coordination_id = offering.subject.coordination_id
        semester = offering.dsd_semester
        can_assign = cell_writable(self.request.user, ASSIGNMENT_EDIT, semester, coordination_id)
        needs_choice = can_assign and any(
            unit.teacher_id is None and unit.pk not in stale for unit in units
        )
        candidates = candidate_teachers(coordination_id) if needs_choice else []
        everyone = {teacher.pk: teacher for teacher in candidates}
        everyone.update({unit.teacher_id: unit.teacher for unit in units if unit.teacher_id})
        loads = teacher_loads(semester.dsd, everyone.values()) if everyone else {}
        rows = []
        for unit in units:
            row = self._row(unit, offering, stale, sizes, can_edit, loads=loads)
            row["unassigned"] = unit.teacher_id is None and unit.pk not in stale
            row["choices"] = []
            if can_assign and row["unassigned"]:
                described = describe_candidates(
                    candidates,
                    loads,
                    coordination_id,
                    semester.number,
                    row["weekly_hours"] or Decimal("0"),
                    None,
                )
                row["choices"] = [(teacher, described[teacher.pk]) for teacher in candidates]
            rows.append(row)
        return rows

    @staticmethod
    def _units(offering):
        """Return the units of an offering with what a row needs."""
        return (
            TeachingUnit.objects.filter(offering=offering)
            .select_related(
                "class_type", "room_type", "teacher", "offering__subject__study_plan__course"
            )
            .prefetch_related(
                "members__class_group_link__class_group",
                "members__subgroup__class_group_link__class_group",
                "members__subgroup__class_group_link__offering",
            )
        )

    def _row(self, unit, offering, stale, sizes, can_edit, with_actions=True, loads=None):
        """Build the row of one unit: hours, turmas, size, room request, stale mark, buttons."""
        hours = {
            load.class_type_id: load.weekly_hours
            for load in unit.offering.subject.class_loads.all()
        }
        members = list(unit.members.all())
        has_groups = any(member.subgroup_id for member in members)
        groups = [
            member.subgroup if member.subgroup_id else member.class_group_link.class_group
            for member in members
        ]
        # The size of a group is not stored (D90): only whole turmas have a number.
        counted = [] if has_groups else [sizes[group.pk] for group in groups if group.pk in sizes]
        return {
            "unit": unit,
            "weekly_hours": hours.get(unit.class_type_id),
            "teacher_load": (loads or {}).get(unit.teacher_id),
            "teacher_link": unit.teacher_id is not None
            and unit.teacher.coordination_id in self._sheet_coordinations,
            "teacher_status": (
                load_text(loads[unit.teacher_id]) if loads and unit.teacher_id in loads else ""
            ),
            "groups": groups,
            "students": sum(size.students for size in counted) if counted else None,
            "provisional": any(size.provisional for size in counted),
            "stale": unit.pk in stale,
            "has_groups": has_groups,
            "actions": self._actions(offering, unit, members, can_edit) if with_actions else [],
            "room_warnings": (
                room_request_warnings(unit, unit_students(unit)) if unit.room_capacity else []
            ),
            "selectable": can_edit and unit.pk not in stale,
        }

    @staticmethod
    def _actions(offering, unit, members, can_edit):
        """Return the buttons of a unit row: ``[{"url", "label"}]``, empty if none (D86, D90, D91).

        A whole turma alone in its unit can be divided; the first group of a divided turma can
        change the number of groups, even when that group is in a merge (the URL names the
        offering of the group's own turma, which may be another course's, D92); every member of
        a merge can be separated.
        """
        if not can_edit:
            return []
        actions = [
            {
                "url": reverse("dsd:unit_teacher", args=[offering.pk, unit.pk]),
                "label": _("Mudar ou retirar docente")
                if unit.teacher_id
                else _("Atribuir docente"),
            },
            {
                "url": reverse("dsd:unit_room", args=[offering.pk, unit.pk]),
                "label": _("Alterar pedido de sala") if unit.room_capacity else _("Pedir sala"),
            },
        ]
        for member in members:
            if member.subgroup_id:
                if member.subgroup.number == 1:
                    link = member.subgroup.class_group_link
                    url = reverse(
                        "dsd:offering_groups",
                        args=[link.offering_id, link.pk, member.class_type_id],
                    )
                    actions.append({"url": url, "label": _("Alterar n.º de grupos")})
            elif len(members) == 1:
                url = reverse(
                    "dsd:offering_groups",
                    args=[
                        member.class_group_link.offering_id,
                        member.class_group_link_id,
                        member.class_type_id,
                    ],
                )
                actions.append({"url": url, "label": _("Dividir em grupos")})
            if len(members) > 1:
                url = reverse(
                    "dsd:offering_separate", args=[offering.pk, member.unit_id, member.pk]
                )
                actions.append(
                    {"url": url, "label": _("Separar") + f" {member.turma_link.class_group}"}
                )
        return actions


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


class _UnitEditMixin(PageMixin, LoginRequiredMixin):
    """Common part of the merge and separate screens: the offering and the permission checks.

    Users who cover no coordination get 403 before anything is looked up, and then the ones who
    do not cover the coordination of the offering (D69); the offering of the URL is 404 after.
    """

    permission_code = TEACHING_UNIT_EDIT

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who cover no coordination, then those who do not cover this one."""
        if request.user.is_authenticated:
            if not registry.coordination_ids(request.user, self.permission_code):
                raise PermissionDenied
            registry.require_on_coordination(
                request.user, self.permission_code, self.offering.subject.coordination_id
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


class OfferingMergeView(_UnitEditMixin, FormView):
    """Merge the selected units of an offering; ask for the room capacity (T3.3b, D91).

    The page lists the members and the sum of the students (a guide, provisional while
    estimated) and, to who may read them, the room quantities (D64). The units come from the
    query string on GET and from hidden fields on POST.
    """

    form_class = MergeForm
    template_name = "dsd/merge_form.html"
    title = _("Juntar unidades")

    @cached_property
    def units(self) -> list[TeachingUnit]:
        """The units asked for, all of this offering; unknown ones are a 404."""
        source = self.request.POST if self.request.method == "POST" else self.request.GET
        ids = [int(pk) for pk in source.getlist("units") if pk.isdigit()]
        units = list(
            TeachingUnit.objects.filter(
                offering__dsd_semester=self.offering.dsd_semester, pk__in=ids
            )
            .select_related("class_type", "offering__subject__study_plan__course")
            .order_by("pk")
        )
        if len(units) != len(set(ids)):
            raise Http404
        return units

    def get(self, request, *args, **kwargs):
        """Show the confirmation; with fewer than two units go back with a message."""
        if len(self.units) < 2:
            messages.error(request, _("Escolha duas ou mais unidades para juntar."))
            return redirect("dsd:offering_detail", pk=self.offering.pk)
        return super().get(request, *args, **kwargs)

    @cached_property
    def students(self):
        """The sum of the students and whether it is provisional, or the error text."""
        members = list(
            TeachingUnitMember.objects.filter(unit__in=self.units).select_related(
                "unit__offering__dsd_semester__dsd__academic_year",
                "class_group_link__class_group",
                "subgroup__class_group_link__class_group",
            )
        )
        try:
            return merged_students(members), None
        except ValidationError as error:
            return None, " ".join(error.messages)

    def get_form_kwargs(self):
        """Start from the sum of the students as the capacity and the versions seen."""
        kwargs = super().get_form_kwargs()
        if "data" not in kwargs:
            total, _error = self.students
            seen = ",".join(f"{unit.pk}:{unit.version}" for unit in self.units)
            kwargs["initial"] = {
                "room_capacity": total,
                "seen": seen,
                "host": self.units[0].pk,
            }
        kwargs["units"] = self.units
        kwargs["has_load_difference"] = bool(self.load_differences)
        return kwargs

    @cached_property
    def load_differences(self):
        """The weekly hours of each subject when they differ, else empty (Q8, D92)."""
        return merge_load_differences(self.units)

    def get_context_data(self, **kwargs):
        """Add the units, the sum, the room quantities (to who may read them) and the way back."""
        context = super().get_context_data(**kwargs)
        total, error = self.students
        context.update(
            {
                "offering": self.offering,
                "units": self.units,
                "students": total,
                "students_error": error,
                "load_differences": self.load_differences,
                "rooms": (
                    room_summary(min_capacity=total)
                    if total and registry.can(self.request.user, "room.view")
                    else None
                ),
                "can_see_rooms": registry.can(self.request.user, "room.view"),
                "cancel_url": reverse("dsd:offering_detail", args=[self.offering.pk]),
            }
        )
        return context

    def form_valid(self, form):
        """Merge the units, or show the error on the form."""
        data = form.cleaned_data
        try:
            merge_units(
                self.request.user,
                self.units,
                data["room_capacity"],
                data["room_type"],
                data["reason"],
                data["seen"] or None,
                host=next((unit for unit in self.units if str(unit.pk) == data["host"]), None),
                accept_load_difference=data.get("accept_load_difference", False),
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Unidades juntadas."))
        return redirect("dsd:offering_detail", pk=self.offering.pk)


class OfferingSeparateView(_UnitEditMixin, FormView):
    """Take one member out of a merge, with a reason (T3.3b, D91, D40)."""

    form_class = SeparateForm
    template_name = "dsd/separate_form.html"
    title = _("Separar da junção")

    @cached_property
    def unit(self) -> TeachingUnit:
        """The merged unit of the URL; it must belong to the offering."""
        return get_object_or_404(
            TeachingUnit.objects.select_related("class_type"),
            pk=self.kwargs["unit_pk"],
            offering=self.offering,
        )

    @cached_property
    def member(self) -> TeachingUnitMember:
        """The member of the URL; it must belong to the unit."""
        return get_object_or_404(
            TeachingUnitMember.objects.select_related(
                "class_group_link__class_group", "subgroup__class_group_link__class_group"
            ),
            pk=self.kwargs["member_pk"],
            unit=self.unit,
        )

    def get_form_kwargs(self):
        """Carry the version of the unit the user saw."""
        kwargs = super().get_form_kwargs()
        if "data" not in kwargs:
            kwargs["initial"] = {"seen": self.unit.version}
        return kwargs

    def get_context_data(self, **kwargs):
        """Say who is being separated, and from which unit."""
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "offering": self.offering,
                "unit": self.unit,
                "member": self.member,
                "cancel_url": reverse("dsd:offering_detail", args=[self.offering.pk]),
            }
        )
        return context

    def form_valid(self, form):
        """Separate the member, or show the error on the form."""
        data = form.cleaned_data
        try:
            separate_member(self.request.user, self.unit, self.member, data["reason"], data["seen"])
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Membro separado."))
        return redirect("dsd:offering_detail", pk=self.offering.pk)


class UnitRoomView(_UnitEditMixin, FormView):
    """Ask for the room a teaching unit needs: a capacity and, optionally, a type (T3.5, Q9).

    Same permission and cell rules as the other unit edits (D86). The page never shows a
    concrete room (D64); warnings are shown on the offering page.
    """

    form_class = RoomRequestForm
    template_name = "dsd/room_form.html"
    title = _("Pedir sala")

    @cached_property
    def unit(self) -> TeachingUnit:
        """The unit of the URL; it must belong to the offering."""
        return get_object_or_404(
            TeachingUnit.objects.select_related("class_type", "room_type"),
            pk=self.kwargs["unit_pk"],
            offering=self.offering,
        )

    def get_form_kwargs(self):
        """Start from the current request, or the students of the unit as a suggestion."""
        kwargs = super().get_form_kwargs()
        kwargs["changing"] = self.unit.room_capacity is not None
        if "data" not in kwargs:
            kwargs["initial"] = {
                "room_capacity": self.unit.room_capacity or unit_students(self.unit),
                "room_type": self.unit.room_type_id,
                "seen": self.unit.version,
            }
        return kwargs

    def get_context_data(self, **kwargs):
        """Say which unit is asking, and the students it has (a guide)."""
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "offering": self.offering,
                "unit": self.unit,
                "students": unit_students(self.unit),
                "cancel_url": reverse("dsd:offering_detail", args=[self.offering.pk]),
            }
        )
        return context

    def form_valid(self, form):
        """Save the request, or show the error on the form."""
        data = form.cleaned_data
        try:
            set_room_request(
                self.request.user,
                self.unit,
                data["room_capacity"],
                data["room_type"],
                data["reason"],
                data["seen"],
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Pedido de sala guardado."))
        return redirect("dsd:offering_detail", pk=self.offering.pk)


class UnitTeacherView(_UnitEditMixin, FormView):
    """Give a teaching unit its teacher, change it or take it off (T5.1b, D94).

    The choices are the active teachers of the coordination of the subject, each with the annual
    hours and the state of the load they would have, to help decide. Choosing nobody takes the
    teacher off. Same cell rules as the other edits (D86).
    """

    permission_code = ASSIGNMENT_EDIT
    form_class = TeacherAssignForm
    template_name = "dsd/teacher_form.html"
    title = _("Docente da unidade")

    @cached_property
    def unit(self) -> TeachingUnit:
        """The unit of the URL; it must belong to the offering."""
        return get_object_or_404(
            TeachingUnit.objects.select_related("class_type", "teacher"),
            pk=self.kwargs["unit_pk"],
            offering=self.offering,
        )

    @cached_property
    def candidates(self) -> list[Teacher]:
        """The active teachers of the coordination of the subject, plus the current teacher."""
        return candidate_teachers(self.offering.subject.coordination_id, self.unit.teacher)

    @cached_property
    def unit_weekly_hours(self) -> Decimal:
        """The weekly hours of the unit: those of its class type in the subject's load."""
        return next(
            (
                load.weekly_hours
                for load in self.offering.subject.class_loads.all()
                if load.class_type_id == self.unit.class_type_id
            ),
            Decimal("0"),
        )

    def descriptions(self) -> dict[int, str]:
        """Describe each candidate: the annual hours and the state they would have (T5.1b).

        For a teacher who does not have the unit, the hours of the unit are added to the load they
        have; the current teacher already counts it, so their load is shown as it is. A teacher
        who is no longer eligible is marked.
        """
        loads = teacher_loads(self.offering.dsd_semester.dsd, self.candidates)
        return describe_candidates(
            self.candidates,
            loads,
            self.offering.subject.coordination_id,
            self.offering.dsd_semester.number,
            self.unit_weekly_hours,
            self.unit.teacher_id,
        )

    def get_form_kwargs(self):
        """Give the form the candidates with their load, and start from the current teacher."""
        kwargs = super().get_form_kwargs()
        kwargs["teachers"] = self.candidates
        kwargs["descriptions"] = self.descriptions()
        kwargs["changing"] = self.unit.teacher_id is not None
        if "data" not in kwargs:
            kwargs["initial"] = {"teacher": self.unit.teacher_id, "seen": self.unit.version}
        return kwargs

    def get_context_data(self, **kwargs):
        """Say which unit is being given a teacher."""
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "offering": self.offering,
                "unit": self.unit,
                "cancel_url": reverse("dsd:offering_detail", args=[self.offering.pk]),
            }
        )
        return context

    def form_valid(self, form):
        """Give, change or remove the teacher, or show the error on the form."""
        data = form.cleaned_data
        try:
            if data["teacher"] is None:
                unassign_teacher(self.request.user, self.unit, data["reason"], data["seen"])
            else:
                assign_teacher(
                    self.request.user, self.unit, data["teacher"], data["reason"], data["seen"]
                )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Docente guardado."))
        return redirect("dsd:offering_detail", pk=self.offering.pk)


class TeacherSheetView(PageMixin, LoginRequiredMixin, TemplateView):
    """The sheet of a teacher in a DSD: lessons, load per semester, activities (T5.3, T6.3).

    It shows, for each semester, the lessons the teacher gives, the teaching hours, the
    preparation and the other activities, then the annual teaching hours with their state and
    the general total (D95). The teacher reads their own sheet and whoever covers their
    coordination reads it too (``dsd.teacher.view``, D09, D69). The teacher only reads: the
    management notes (the reason for a low load and the board's comment, the pending extra hours)
    and every button are for who covers the coordination, and the buttons also follow the state of
    the cell (D86).
    """

    template_name = "dsd/teacher_sheet.html"

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who read no sheet, then those who may not read this one."""
        if request.user.is_authenticated:
            if not (
                registry.own_teacher_ids(request.user, TEACHER_SHEET_VIEW)
                or registry.coordination_ids(request.user, TEACHER_SHEET_VIEW)
            ):
                raise PermissionDenied
            if not registry.can_on_teacher(request.user, TEACHER_SHEET_VIEW, self.teacher):
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def manages(self) -> bool:
        """Whether the user covers the teacher's coordination (not only reads their own sheet)."""
        return registry.can_on_coordination(
            self.request.user, TEACHER_SHEET_VIEW, self.teacher.coordination_id
        )

    def _lessons(self) -> dict[int, list[dict]]:
        """The lessons the teacher gives in the DSD, by semester number (T6.3).

        Each lesson has its subject and course, class type, weekly hours, the turmas or groups
        it is given to and whether it puts several of them together.
        """
        units = (
            TeachingUnit.objects.filter(offering__dsd_semester__dsd=self.dsd, teacher=self.teacher)
            .select_related(
                "class_type",
                "offering__subject__study_plan__course",
                "offering__dsd_semester",
            )
            .prefetch_related(
                "offering__subject__class_loads",
                "members__class_group_link__class_group",
                "members__subgroup__class_group_link__class_group",
            )
            .order_by(
                "offering__dsd_semester__number",
                "offering__subject__code",
                "class_type__position",
                "pk",
            )
        )
        lessons: dict[int, list[dict]] = {}
        for unit in units:
            members = list(unit.members.all())
            hours = next(
                (
                    load.weekly_hours
                    for load in unit.offering.subject.class_loads.all()
                    if load.class_type_id == unit.class_type_id
                ),
                None,
            )
            lessons.setdefault(unit.offering.dsd_semester.number, []).append(
                {
                    "unit": unit,
                    "subject": unit.offering.subject,
                    "course": unit.offering.subject.study_plan.course,
                    "weekly_hours": hours,
                    "groups": [
                        member.subgroup
                        if member.subgroup_id
                        else member.class_group_link.class_group
                        for member in members
                    ],
                    "merged": len(members) > 1,
                }
            )
        return lessons

    @cached_property
    def dsd(self) -> Dsd:
        """The DSD of the URL, read after the permission check."""
        return get_object_or_404(Dsd.objects.select_related("academic_year"), pk=self.kwargs["pk"])

    @cached_property
    def teacher(self) -> Teacher:
        """The teacher of the URL."""
        return get_object_or_404(
            Teacher.objects.select_related("coordination"), pk=self.kwargs["teacher_pk"]
        )

    def _activities_of(self, semester, activities) -> list[OtherActivity]:
        """The activities of a semester, each marked with whether the user may change it.

        The cell of an activity is the coordination stored with it, which can differ from the
        teacher's current one after a transfer; the change and remove screens use that cell.
        """
        mine = [a for a in activities if a.dsd_semester_id == semester.pk]
        for activity in mine:
            activity.can_edit = cell_writable(
                self.request.user, ASSIGNMENT_EDIT, semester, activity.coordination_id
            )
        return mine

    def get_context_data(self, **kwargs):
        """Build the load and one block per semester with its activities."""
        context = super().get_context_data(**kwargs)
        load = teacher_loads(self.dsd, [self.teacher])[self.teacher.pk]
        activities = OtherActivity.objects.filter(
            dsd_semester__dsd=self.dsd, teacher=self.teacher
        ).select_related("dsd_semester")
        extra_record = AcceptedExtraHours.objects.filter(dsd=self.dsd, teacher=self.teacher).first()
        minimum_record = (
            BelowMinimumReason.objects.filter(dsd=self.dsd, teacher=self.teacher)
            .select_related("review")
            .first()
        )
        blocks = []
        lessons = self._lessons()
        for index, semester in enumerate(self.dsd.semesters.order_by("number")):
            blocks.append(
                {
                    "semester": semester,
                    "lessons": lessons.get(semester.number, []),
                    "teaching": load.assessment.semester_weekly_hours[index],
                    "preparation": load.preparation[index],
                    "other": load.other_hours[index],
                    "activities": self._activities_of(semester, activities),
                    "can_edit": cell_writable(
                        self.request.user, ASSIGNMENT_EDIT, semester, self.teacher.coordination_id
                    ),
                }
            )
        context.update(
            {
                "title": self.teacher.name,
                "dsd": self.dsd,
                "teacher": self.teacher,
                "load": load,
                "status": load_text(load) if self.manages else status_text(load.assessment),
                "manages": self.manages,
                "extra_record": extra_record,
                "minimum_record": minimum_record,
                "can_edit_minimum": load.minimum_reason != MinimumReasonState.NOT_NEEDED
                and any(
                    cell_writable(
                        self.request.user, ASSIGNMENT_EDIT, semester, self.teacher.coordination_id
                    )
                    for semester in self.dsd.semesters.all()
                ),
                "can_edit_extra": any(
                    cell_writable(
                        self.request.user, ASSIGNMENT_EDIT, semester, self.teacher.coordination_id
                    )
                    for semester in self.dsd.semesters.all()
                ),
                "blocks": blocks,
            }
        )
        return context


class _ActivityMixin(PageMixin, LoginRequiredMixin):
    """Common part of the activity screens: permission on the coordination, then the lookups.

    Users who cover no coordination get 403 before anything is looked up, and then the ones
    who do not cover the coordination of the teacher or of the activity (D69).
    """

    template_name = "dsd/activity_form.html"
    permission_code = ASSIGNMENT_EDIT

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who cover no coordination, then those who do not cover this one."""
        if request.user.is_authenticated:
            if not registry.coordination_ids(request.user, self.permission_code):
                raise PermissionDenied
            registry.require_on_coordination(
                request.user, self.permission_code, self.coordination_id
            )
        return super().dispatch(request, *args, **kwargs)

    @property
    def coordination_id(self) -> int:
        """The coordination that owns the data being written."""
        raise NotImplementedError

    @property
    def teacher(self) -> Teacher:
        """The teacher the activity belongs to."""
        raise NotImplementedError

    @property
    def dsd(self) -> Dsd:
        """The DSD."""
        raise NotImplementedError

    def sheet_url(self) -> str:
        """The sheet of the teacher, where every activity screen goes back to."""
        return reverse("dsd:teacher_sheet", args=[self.dsd.pk, self.teacher.pk])

    def get_context_data(self, **kwargs):
        """Name the teacher and go back to the sheet on cancel."""
        context = super().get_context_data(**kwargs)
        context.update(
            {"teacher": self.teacher, "cancel_url": self.sheet_url(), "title": self.title}
        )
        return context


class ActivityAddView(_ActivityMixin, FormView):
    """Enter an activity of the non-teaching component in a semester (T5.3, D15)."""

    form_class = ActivityForm
    title = _("Nova atividade")

    @cached_property
    def teacher(self) -> Teacher:
        """The teacher of the URL."""
        return get_object_or_404(
            Teacher.objects.select_related("coordination"), pk=self.kwargs["teacher_pk"]
        )

    @cached_property
    def dsd(self) -> Dsd:
        """The DSD of the URL."""
        return get_object_or_404(Dsd.objects.select_related("academic_year"), pk=self.kwargs["pk"])

    @cached_property
    def semester(self) -> DsdSemester:
        """The semester of the URL (1 or 2) of this DSD."""
        return get_object_or_404(self.dsd.semesters, number=self.kwargs["number"])

    @property
    def coordination_id(self) -> int:
        """The coordination of the teacher."""
        return self.teacher.coordination_id

    def form_valid(self, form):
        """Add the activity or show the error on the form."""
        data = form.cleaned_data
        try:
            add_activity(
                self.request.user,
                self.teacher,
                self.semester,
                data["kind"],
                data["description"],
                data["weekly_hours"],
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Atividade guardada."))
        return redirect(self.sheet_url())


class _ExistingActivityMixin(_ActivityMixin):
    """The activity of the URL, with its teacher and DSD, for the change and remove screens."""

    @cached_property
    def activity(self) -> OtherActivity:
        """The activity of the URL."""
        return get_object_or_404(
            OtherActivity.objects.select_related(
                "teacher__coordination", "dsd_semester__dsd__academic_year"
            ),
            pk=self.kwargs["pk"],
        )

    @property
    def teacher(self) -> Teacher:
        """The teacher of the activity."""
        return self.activity.teacher

    @property
    def dsd(self) -> Dsd:
        """The DSD of the activity."""
        return self.activity.dsd_semester.dsd

    @property
    def coordination_id(self) -> int:
        """The coordination stored with the activity (its cell)."""
        return self.activity.coordination_id

    def get_context_data(self, **kwargs):
        """Say which activity this is."""
        context = super().get_context_data(**kwargs)
        context["activity"] = self.activity
        return context


class ActivityEditView(_ExistingActivityMixin, FormView):
    """Change an activity: type, description or hours, with a reason (T5.3, D40, D54)."""

    form_class = ActivityEditForm
    title = _("Alterar atividade")

    def get_initial(self):
        """Start from the stored values and the version the user is seeing."""
        activity = self.activity
        return {
            "kind": activity.kind,
            "description": activity.description,
            "weekly_hours": activity.weekly_hours,
            "seen": activity.version,
        }

    def form_valid(self, form):
        """Save the change or show the error on the form."""
        data = form.cleaned_data
        try:
            edit_activity(
                self.request.user,
                self.activity,
                data["kind"],
                data["description"],
                data["weekly_hours"],
                data["reason"],
                data["seen"],
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Atividade guardada."))
        return redirect(self.sheet_url())


class ActivityRemoveView(_ExistingActivityMixin, FormView):
    """Remove an activity, with a reason (T5.3, D40)."""

    form_class = ActivityRemoveForm
    title = _("Remover atividade")

    def get_initial(self):
        """Carry the version the user is seeing."""
        return {"seen": self.activity.version}

    def form_valid(self, form):
        """Remove the activity or show the error on the form."""
        data = form.cleaned_data
        try:
            remove_activity(self.request.user, self.activity, data["reason"], data["seen"])
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Atividade removida."))
        return redirect(self.sheet_url())


class ExtraAcceptView(_ActivityMixin, FormView):
    """Record, or change, the extra hours a teacher accepted in a DSD (T5.4, D13)."""

    form_class = ExtraAcceptForm
    title = _("Horas extra aceites")

    @cached_property
    def teacher(self) -> Teacher:
        """The teacher of the URL."""
        return get_object_or_404(
            Teacher.objects.select_related("coordination"), pk=self.kwargs["teacher_pk"]
        )

    @cached_property
    def dsd(self) -> Dsd:
        """The DSD of the URL."""
        return get_object_or_404(Dsd.objects.select_related("academic_year"), pk=self.kwargs["pk"])

    @property
    def coordination_id(self) -> int:
        """The coordination of the teacher."""
        return self.teacher.coordination_id

    @cached_property
    def existing(self) -> AcceptedExtraHours | None:
        """The record of the teacher in this DSD, if any."""
        return AcceptedExtraHours.objects.filter(dsd=self.dsd, teacher=self.teacher).first()

    def get_form_kwargs(self):
        """Start from the recorded hours and version, if there is a record."""
        kwargs = super().get_form_kwargs()
        kwargs["existing"] = self.existing is not None
        if "data" not in kwargs and self.existing is not None:
            kwargs["initial"] = {"hours": self.existing.hours, "seen": self.existing.version}
        return kwargs

    def get_context_data(self, **kwargs):
        """Show the record being changed, if any."""
        context = super().get_context_data(**kwargs)
        context["extra_record"] = self.existing
        return context

    def form_valid(self, form):
        """Record the hours or show the error on the form."""
        data = form.cleaned_data
        try:
            set_accepted_extra(
                self.request.user,
                self.teacher,
                self.dsd,
                data["hours"],
                data["reason"],
                data["seen"],
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Horas extra aceites guardadas."))
        return redirect(self.sheet_url())


class ExtraClearView(_ActivityMixin, FormView):
    """Remove the record of accepted extra hours, with a reason (T5.4, D40)."""

    form_class = ActivityRemoveForm
    title = _("Remover horas extra aceites")

    @cached_property
    def record(self) -> AcceptedExtraHours:
        """The record of the URL."""
        return get_object_or_404(
            AcceptedExtraHours.objects.select_related(
                "teacher__coordination", "dsd__academic_year"
            ),
            pk=self.kwargs["pk"],
        )

    @property
    def teacher(self) -> Teacher:
        """The teacher of the record."""
        return self.record.teacher

    @property
    def dsd(self) -> Dsd:
        """The DSD of the record."""
        return self.record.dsd

    @property
    def coordination_id(self) -> int:
        """The current coordination of the teacher: the record follows them (D96)."""
        return self.record.teacher.coordination_id

    def get_initial(self):
        """Carry the version the user is seeing."""
        return {"seen": self.record.version}

    def form_valid(self, form):
        """Remove the record or show the error on the form."""
        data = form.cleaned_data
        try:
            clear_accepted_extra(self.request.user, self.record, data["reason"], data["seen"])
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Horas extra aceites removidas."))
        return redirect(self.sheet_url())


class MinimumReasonView(_ActivityMixin, FormView):
    """Register, or change, the reason for a teacher whose load is below the minimum (T5.5)."""

    form_class = MinimumReasonForm
    title = _("Motivo abaixo da mínima")

    @cached_property
    def teacher(self) -> Teacher:
        """The teacher of the URL."""
        return get_object_or_404(
            Teacher.objects.select_related("coordination"), pk=self.kwargs["teacher_pk"]
        )

    @cached_property
    def dsd(self) -> Dsd:
        """The DSD of the URL."""
        return get_object_or_404(Dsd.objects.select_related("academic_year"), pk=self.kwargs["pk"])

    @property
    def coordination_id(self) -> int:
        """The coordination of the teacher."""
        return self.teacher.coordination_id

    @cached_property
    def existing(self) -> BelowMinimumReason | None:
        """The reason of the teacher in this DSD, if any."""
        return BelowMinimumReason.objects.filter(dsd=self.dsd, teacher=self.teacher).first()

    def get_form_kwargs(self):
        """Start from the stored text and version, if there is a reason."""
        kwargs = super().get_form_kwargs()
        kwargs["existing"] = self.existing is not None
        if "data" not in kwargs and self.existing is not None:
            kwargs["initial"] = {"text": self.existing.text, "seen": self.existing.version}
        return kwargs

    def form_valid(self, form):
        """Save the reason or show the error on the form."""
        data = form.cleaned_data
        try:
            set_minimum_reason(
                self.request.user, self.teacher, self.dsd, data["text"], data["seen"]
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Motivo guardado."))
        return redirect(self.sheet_url())


class MinimumReviewListView(PageMixin, LoginRequiredMixin, TemplateView):
    """The teachers below the minimum in the Faculties of the Executive Board, with reasons (T5.5).

    Only the board sees it (``dsd.below_minimum.review``, D69); it lists the active teachers of
    the coordinations the user covers whose annual load is below the minimum, each with the reason
    and its state, and a link to decide.
    """

    template_name = "dsd/minimum_review_list.html"
    title = _("Docentes abaixo da carga mínima")

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who review nothing."""
        if request.user.is_authenticated and not registry.coordination_ids(
            request.user, REVIEW_MINIMUM
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Build one row per teacher below the minimum or with a reason."""
        context = super().get_context_data(**kwargs)
        dsd = get_object_or_404(Dsd.objects.select_related("academic_year"), pk=self.kwargs["pk"])
        covered = registry.coordination_ids(self.request.user, REVIEW_MINIMUM)
        teachers = list(
            Teacher.objects.filter(coordination_id__in=covered, is_active=True)
            .select_related("coordination")
            .order_by("name")
        )
        loads = teacher_loads(dsd, teachers)
        reasons = {
            reason.teacher_id: reason
            for reason in BelowMinimumReason.objects.filter(
                dsd=dsd, teacher__in=teachers
            ).select_related("review")
        }
        rows = []
        for teacher in teachers:
            load = loads[teacher.pk]
            if load.minimum_reason == MinimumReasonState.NOT_NEEDED:
                continue
            rows.append(
                {
                    "teacher": teacher,
                    "hours": load.assessment.weekly_hours,
                    "state": minimum_reason_text(load.minimum_reason),
                    "reason": reasons.get(teacher.pk),
                }
            )
        context.update({"title": self.title, "dsd": dsd, "rows": rows})
        return context


class MinimumReviewView(PageMixin, LoginRequiredMixin, FormView):
    """Accept or refuse the reason of a teacher below the minimum (T5.5, D16, D97)."""

    form_class = MinimumReviewForm
    template_name = "dsd/minimum_review_form.html"
    title = _("Avaliar motivo")

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who review nothing, then those who do not cover this teacher."""
        if request.user.is_authenticated:
            if not registry.coordination_ids(request.user, REVIEW_MINIMUM):
                raise PermissionDenied
            registry.require_on_coordination(
                request.user, REVIEW_MINIMUM, self.reason.teacher.coordination_id
            )
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def reason(self) -> BelowMinimumReason:
        """The reason of the URL."""
        return get_object_or_404(
            BelowMinimumReason.objects.select_related(
                "teacher__coordination", "dsd__academic_year"
            ),
            pk=self.kwargs["pk"],
        )

    def get_initial(self):
        """Carry the version of the text the board is seeing."""
        return {"seen": self.reason.version}

    def get_context_data(self, **kwargs):
        """Show the teacher and the text being reviewed."""
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "title": self.title,
                "reason": self.reason,
                "cancel_url": reverse("dsd:minimum_review_list", args=[self.reason.dsd_id]),
            }
        )
        return context

    def form_valid(self, form):
        """Save the decision or show the error on the form."""
        data = form.cleaned_data
        try:
            review_minimum_reason(
                self.request.user, self.reason, data["decision"], data["comment"], data["seen"]
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Decisão guardada."))
        return redirect("dsd:minimum_review_list", pk=self.reason.dsd_id)


class CoordinationOverviewView(PageMixin, LoginRequiredMixin, TemplateView):
    """What needs attention in a coordination and each teacher's load in a bar (T6.1, D20, D98).

    Only who covers the coordination reads it (``dsd.coordination.view``, D69): the coordinator of
    it, and the manager and the Executive Board of its Faculty. The semester comes from
    ``?semester=1|2`` (the first by default).
    """

    template_name = "dsd/coordination_overview.html"

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who cover no coordination, then those who do not cover this one."""
        if request.user.is_authenticated:
            if not registry.coordination_ids(request.user, "dsd.coordination.view"):
                raise PermissionDenied
            registry.require_on_coordination(
                request.user, "dsd.coordination.view", self.kwargs["coordination_pk"]
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Compute the overview and describe each item with the teachers it concerns."""
        context = super().get_context_data(**kwargs)
        dsd = get_object_or_404(Dsd.objects.select_related("academic_year"), pk=self.kwargs["pk"])
        coordination = get_object_or_404(
            Coordination.objects.select_related("faculty"), pk=self.kwargs["coordination_pk"]
        )
        number = self.request.GET.get("semester", "1")
        if number not in ("1", "2"):
            raise Http404
        try:
            result = coordination_overview(dsd, int(number), coordination)
        except DsdSemester.DoesNotExist:
            raise Http404 from None
        by_id = {row.teacher.pk: row.teacher for row in result.rows}
        covered = registry.coordination_ids(self.request.user, TEACHER_SHEET_VIEW)
        own = registry.own_teacher_ids(self.request.user, TEACHER_SHEET_VIEW)
        context.update(
            {
                "title": coordination.name,
                "dsd": dsd,
                "coordination": coordination,
                "overview": result,
                "openable": {
                    row.teacher.pk
                    for row in result.rows
                    if row.teacher.coordination_id in covered or row.teacher.pk in own
                },
                "semester_number": int(number),
                "items": [
                    {
                        "text": attention_text(item),
                        "kind": item.kind,
                        "teachers": [by_id[pk] for pk in item.teacher_ids if pk in by_id],
                    }
                    for item in result.items
                ],
            }
        )
        return context


class UnitTeacherInlineView(OfferingDetailView):
    """Give a teacher to a unit without one from its row on the subject page (T6.2, D50, D94).

    It takes only POST. With HTMX it answers with the updated row; without it, it saves and goes
    back to the page, so the selector also works without JavaScript. It only gives a teacher to a
    unit that has none: changing or removing one needs a reason (D40) and stays on the form page.
    The write is ``assign_teacher``, which checks the permission, the cell and the version.
    """

    http_method_names = ["post"]
    template_name = "dsd/_unit_row.html"

    def post(self, request, *args, **kwargs):
        """Assign the chosen teacher, then show the row (HTMX) or go back to the page."""
        if not registry.coordination_ids(request.user, ASSIGNMENT_EDIT):
            raise PermissionDenied
        offering = get_object_or_404(
            Offering.objects.select_related(
                "subject__coordination",
                "subject__study_plan__course",
                "dsd_semester__dsd__academic_year",
            ),
            pk=self.kwargs["pk"],
        )
        registry.require_on_coordination(
            request.user, ASSIGNMENT_EDIT, offering.subject.coordination_id
        )
        unit = get_object_or_404(TeachingUnit, pk=self.kwargs["unit_pk"], offering=offering)
        error = self._assign(request, offering, unit)
        if not request.headers.get("HX-Request"):
            if error:
                messages.error(request, error)
            else:
                messages.success(request, _("Docente guardado."))
            return redirect("dsd:offering_detail", pk=offering.pk)
        context = self._row_context(request, offering, unit, error)
        if context is None:
            # The unit is gone (its turma was divided or merged meanwhile): reload the page.
            return HttpResponse(headers={"HX-Refresh": "true"})
        return self.render_to_response(context)

    def _assign(self, request, offering, unit) -> str:
        """Give the unit the teacher of the request; return an error text, or an empty one."""
        if unit.teacher_id is not None:
            return str(_("A unidade já tem docente: use «Alterar» para mudar ou retirar."))
        candidates = {
            teacher.pk: teacher for teacher in candidate_teachers(offering.subject.coordination_id)
        }
        teacher_id = request.POST.get("teacher", "")
        teacher = candidates.get(int(teacher_id)) if teacher_id.isdigit() else None
        seen = request.POST.get("seen", "")
        if teacher is None:
            return str(_("Escolha um docente da lista."))
        if not seen.isdigit():
            return str(_("Dados do formulário inválidos."))
        try:
            assign_teacher(request.user, unit, teacher, "", int(seen))
        except ValidationError as error:
            return " ".join(error.messages)
        return ""

    def _row_context(self, request, offering, unit, error: str) -> dict | None:
        """Build the context to draw the row of one unit again, with an error if there is one.

        Returns ``None`` if the unit no longer exists.
        """
        unit = self._units(offering).filter(pk=unit.pk).first()
        if unit is None:
            return None
        coordination_id = offering.subject.coordination_id
        stale = stale_unit_ids(offering.dsd_semester, coordination_id)
        sizes = class_group_sizes(offering.dsd_semester.dsd.academic_year)
        can_edit = cell_writable(
            request.user, TEACHING_UNIT_EDIT, offering.dsd_semester, coordination_id
        )
        row = self._unit_rows(offering, [unit], stale, sizes, can_edit)[0]
        row["error"] = error
        return {"row": row, "offering": offering, "can_edit": can_edit, "request": request}


class MySheetView(PageMixin, LoginRequiredMixin, View):
    """Send a teacher to their own sheet in the latest DSD (T6.3, D09).

    Only accounts linked to a teacher record have one; anybody else is refused. When no DSD
    exists there is nothing to show.
    """

    def get(self, request, *args, **kwargs):
        """Redirect to the sheet of the user's teacher in the DSD of the latest year."""
        own = sorted(registry.own_teacher_ids(request.user, TEACHER_SHEET_VIEW))
        if not own:
            raise PermissionDenied
        dsd = Dsd.objects.order_by("-academic_year__start_year").first()
        if dsd is None:
            raise Http404
        return redirect("dsd:teacher_sheet", pk=dsd.pk, teacher_pk=own[0])
