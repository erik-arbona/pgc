"""Screens of the DSD: list and create (T2.1).

Implements: docs/backlog_fase2.md T2.1; D43 (only the manager creates; the coordinator reads).
"""

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from apps.core.generic import ManagedCreateView, ManagedListView

from .forms import DsdForm
from .models import Dsd
from .services import create_dsd


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
