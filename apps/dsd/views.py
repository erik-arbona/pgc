"""Screens of the DSD: list, create, state grid and state change (T2.1, T2.2).

Implements: docs/backlog_fase2.md T2.1 and T2.2; D43 (only the manager creates and changes
the state; the coordinator reads), D86.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, FormView

from apps.academic.models import Coordination
from apps.core.generic import (
    ManagedCreateView,
    ManagedListView,
    ManagedViewMixin,
    add_validation_errors,
)

from .forms import DsdForm, StateChangeForm
from .models import CoordinationSemester, Dsd
from .services import change_state, create_dsd


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
