"""Screens of the tender proposals: propose, read and act (block 5, part 2a).

Implements: docs/especificacao/05_dsd_regras.md – tender proposals; D17, D46, D50 (normal forms),
D86, D97, D105, D106.

The page of a proposal is the same for everybody; the buttons follow the role (the coordinator
withdraws and treats a refused proposal again, the Executive Board decides, the PGC manager
registers the teacher the tender obtained) and the state. The server checks the role and the state
again on every action, and the use cases (``tenders``) check the permission and the cell.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, TemplateView

from apps.core.generic import PageMixin, add_validation_errors
from apps.core.permissions import registry

from .forms import TenderActionForm, TenderProposalForm
from .lifecycle import cell_writable
from .models import TENDER_STATE_CHOICES, Offering, TeachingUnit, TenderProposal
from .services import ASSIGNMENT_EDIT, TENDER_DECIDE, TENDER_FILL, TENDER_VIEW
from .tender_rules import (
    BOARD_ACTIONS,
    COORDINATOR_ACTIONS,
    TenderAction,
    TenderState,
    actions_from,
)
from .tenders import (
    decide_tender,
    fill_tender,
    propose_tender,
    resubmit_tender,
    tender_collaborators,
    withdraw_tender,
)

ACTION_LABELS = {
    TenderAction.WITHDRAW: _("Retirar a proposta"),
    TenderAction.RESUBMIT: _("Tratar de novo e reenviar"),
    TenderAction.APPROVE: _("Aprovar"),
    TenderAction.REFUSE: _("Recusar"),
    TenderAction.INVITE: _("Convidar um colaborador"),
    TenderAction.SEND_TO_TENDER: _("Mandar a concurso"),
    TenderAction.ACCEPT_INVITATION: _("Registar: o docente aceitou"),
    TenderAction.DECLINE_INVITATION: _("Registar: o docente recusou"),
    TenderAction.CANCEL: _("Cancelar o caso"),
    TenderAction.FILL: _("Atribuir o docente obtido por concurso"),
}
_STATE_LABELS = dict(TENDER_STATE_CHOICES)


def coordination_of(proposal: TenderProposal) -> int:
    """The coordination that owns a proposal: that of the subject of its unit (D69)."""
    return proposal.unit.offering.subject.coordination_id


def role_may(user, proposal: TenderProposal, action: TenderAction) -> bool:
    """Whether the user's role may ever do an action on this proposal (not the state, not the cell).

    The coordinator's actions need the assignment permission on the coordination, the board's the
    tender-decision permission and the manager's the tender-filling permission, all by
    coordination (D69).
    """
    coordination_id = coordination_of(proposal)
    if action in COORDINATOR_ACTIONS:
        return registry.can_on_coordination(user, ASSIGNMENT_EDIT, coordination_id)
    if action in BOARD_ACTIONS:
        return registry.can_on_coordination(user, TENDER_DECIDE, coordination_id)
    return registry.can_on_coordination(user, TENDER_FILL, coordination_id)


def offered_actions(user, proposal: TenderProposal) -> list[TenderAction]:
    """The actions to show a user on a proposal: right role, valid state, writable cell.

    The board's decisions need no cell (D97); the coordinator's and the manager's do (D86).
    """
    semester = proposal.unit.offering.dsd_semester
    writable = cell_writable(user, ASSIGNMENT_EDIT, semester, coordination_of(proposal))
    return [
        action
        for action in actions_from(TenderState(proposal.state))
        if role_may(user, proposal, action) and (action in BOARD_ACTIONS or writable)
    ]


class _ProposalMixin(PageMixin, LoginRequiredMixin):
    """Common part of the proposal screens: the proposal of the URL and its read permission."""

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who read no proposal, then those who do not cover this one."""
        if request.user.is_authenticated:
            if not registry.coordination_ids(request.user, TENDER_VIEW):
                raise PermissionDenied
            registry.require_on_coordination(
                request.user, TENDER_VIEW, coordination_of(self.proposal)
            )
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def proposal(self) -> TenderProposal:
        """The proposal of the URL."""
        return get_object_or_404(
            TenderProposal.objects.select_related(
                "unit__class_type",
                "unit__offering__subject__study_plan__course",
                "unit__offering__dsd_semester__dsd__academic_year",
                "suggested_teacher",
                "invited_teacher",
            ),
            pk=self.kwargs["pk"],
        )


class TenderProposeView(PageMixin, LoginRequiredMixin, FormView):
    """Propose a unit without a teacher to tender, with a justification (D17)."""

    form_class = TenderProposalForm
    template_name = "dsd/tender_form.html"
    title = _("Propor a concurso")

    def dispatch(self, request, *args, **kwargs):
        """Refuse users who cover no coordination, then those who do not cover this one."""
        if request.user.is_authenticated:
            if not registry.coordination_ids(request.user, ASSIGNMENT_EDIT):
                raise PermissionDenied
            registry.require_on_coordination(
                request.user, ASSIGNMENT_EDIT, self.offering.subject.coordination_id
            )
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def offering(self) -> Offering:
        """The offering of the URL."""
        return get_object_or_404(
            Offering.objects.select_related(
                "subject__study_plan__course", "dsd_semester__dsd__academic_year"
            ),
            pk=self.kwargs["pk"],
        )

    @cached_property
    def unit(self) -> TeachingUnit:
        """The unit of the URL; it must belong to the offering."""
        return get_object_or_404(
            TeachingUnit.objects.select_related("class_type"),
            pk=self.kwargs["unit_pk"],
            offering=self.offering,
        )

    def get_form_kwargs(self):
        """Offer the collaborators of the coordination as the suggestion."""
        kwargs = super().get_form_kwargs()
        kwargs["collaborators"] = tender_collaborators(self.offering.subject.coordination_id)
        return kwargs

    def get_context_data(self, **kwargs):
        """Say which unit this is about."""
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "title": self.title,
                "offering": self.offering,
                "unit": self.unit,
                "cancel_url": reverse("dsd:offering_detail", args=[self.offering.pk]),
            }
        )
        return context

    def form_valid(self, form):
        """Create the proposal and show it, or show the error on the form."""
        data = form.cleaned_data
        try:
            proposal = propose_tender(
                self.request.user,
                self.unit,
                data["reason_kind"],
                data["justification"],
                data["suggested_teacher"],
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Proposta guardada."))
        return redirect("dsd:tender_detail", pk=proposal.pk)


class TenderDetailView(_ProposalMixin, TemplateView):
    """A proposal with its justification, its state, its history and the actions on it."""

    template_name = "dsd/tender_detail.html"

    def get_context_data(self, **kwargs):
        """Build the page: the case, the history and the buttons of this user."""
        context = super().get_context_data(**kwargs)
        proposal = self.proposal
        unit = proposal.unit
        events = [
            {
                "event": event,
                "from_label": _STATE_LABELS.get(event.from_state, ""),
                "to_label": _STATE_LABELS.get(event.to_state, event.to_state),
            }
            for event in proposal.events.select_related("actor").order_by("pk")
        ]
        context.update(
            {
                "title": _("Proposta de concurso"),
                "proposal": proposal,
                "unit": unit,
                "offering": unit.offering,
                "events": events,
                "actions": [
                    {
                        "label": ACTION_LABELS[action],
                        "url": reverse("dsd:tender_action", args=[proposal.pk, action.value]),
                    }
                    for action in offered_actions(self.request.user, proposal)
                ],
                "offering_url": reverse("dsd:offering_detail", args=[unit.offering_id]),
                # Only when the assignment can really be done: right user and writable cell.
                "to_assign": proposal.state == TenderState.ACCEPTED.value
                and cell_writable(
                    self.request.user,
                    ASSIGNMENT_EDIT,
                    unit.offering.dsd_semester,
                    coordination_of(proposal),
                ),
            }
        )
        return context


class TenderActionView(_ProposalMixin, FormView):
    """Do one action on a proposal: a form for it, then the use case (the roles are checked)."""

    form_class = TenderActionForm
    template_name = "dsd/tender_action_form.html"

    @cached_property
    def action(self) -> TenderAction:
        """The action of the URL; an unknown one is a 404."""
        try:
            return TenderAction(self.kwargs["action"])
        except ValueError:
            raise Http404 from None

    def get_form_class(self):
        """Check the role (403) and then the state (404) before building the form."""
        if not role_may(self.request.user, self.proposal, self.action):
            raise PermissionDenied
        if self.action not in actions_from(TenderState(self.proposal.state)):
            raise Http404
        return super().get_form_class()

    def get_form_kwargs(self):
        """Give the form the action, the collaborators and the teachers that can be chosen."""
        from .teacher_choices import candidate_teachers

        kwargs = super().get_form_kwargs()
        coordination_id = coordination_of(self.proposal)
        kwargs["action"] = self.action
        kwargs["collaborators"] = tender_collaborators(coordination_id)
        kwargs["eligible"] = candidate_teachers(coordination_id)
        if "data" not in kwargs:
            kwargs["initial"] = {
                "seen": self.proposal.version,
                "reason_kind": self.proposal.reason_kind,
                "justification": self.proposal.justification,
                "suggested_teacher": self.proposal.suggested_teacher_id,
            }
        return kwargs

    def get_context_data(self, **kwargs):
        """Name the action and go back to the proposal on cancel."""
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "title": ACTION_LABELS[self.action],
                "proposal": self.proposal,
                "cancel_url": reverse("dsd:tender_detail", args=[self.proposal.pk]),
            }
        )
        return context

    def form_valid(self, form):
        """Run the use case of the action, or show the error on the form."""
        data = form.cleaned_data
        user, proposal, action = self.request.user, self.proposal, self.action
        try:
            if action == TenderAction.WITHDRAW:
                withdraw_tender(user, proposal, data["reason"], data["seen"])
            elif action == TenderAction.RESUBMIT:
                resubmit_tender(
                    user,
                    proposal,
                    data["reason_kind"],
                    data["justification"],
                    data["suggested_teacher"],
                    data["seen"],
                )
            elif action == TenderAction.FILL:
                fill_tender(user, proposal, data["teacher"], data["seen"])
            else:
                decide_tender(
                    user,
                    proposal,
                    action,
                    data.get("comment", ""),
                    data.get("teacher"),
                    data["seen"],
                )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Guardado."))
        return redirect("dsd:tender_detail", pk=proposal.pk)
