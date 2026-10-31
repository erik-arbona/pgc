"""Shared building blocks for the data-entry screens (list, create, edit, delete).

Implements: docs/especificacao/07_arquitetura.md – permissions checked on the server and
audit of every change; D40 (reason), D50 (UI pattern).
Every write goes through ``audited_save`` / ``audited_delete``; updates and deletions need a
reason. Screens work with plain forms (POST, redirect, GET) and need no JavaScript.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .audit import audited_delete, audited_save
from .mixins import PermissionRequiredMixin

PAGE_SIZE = 25
REASON_LABEL = _("Motivo")


class ReasonModelForm(forms.ModelForm):
    """Model form with a ``reason`` field, required when the record already exists (D40)."""

    reason = forms.CharField(
        label=REASON_LABEL,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=_("Obrigatório ao alterar."),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = self.instance.pk is not None


class DeleteReasonForm(forms.Form):
    """Confirmation form of a deletion: the reason is always required."""

    reason = forms.CharField(
        label=REASON_LABEL, widget=forms.Textarea(attrs={"rows": 2}), required=True
    )


class ManagedViewMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Require a session (redirect to login) and then the view's ``permission_action``."""

    title: str = ""

    def get_context_data(self, **kwargs):
        """Add the page title to the context."""
        context = super().get_context_data(**kwargs)
        context["title"] = self.title
        context["cancel_url"] = getattr(self, "success_url", None) or "/"
        return context


class ManagedListView(ManagedViewMixin, ListView):
    """Paginated list (25 per page) restricted to who holds the permission."""

    paginate_by = PAGE_SIZE


def _add_validation_errors(form: forms.Form, error: ValidationError) -> None:
    """Show a ``ValidationError`` raised while saving on the form it came from."""
    if hasattr(error, "error_dict"):
        for field, messages_ in error.message_dict.items():
            form.add_error(field if field in form.fields else None, messages_)
    else:
        form.add_error(None, error.messages)


class AuditedFormMixin(ManagedViewMixin):
    """Save through ``audited_save`` and report model-level errors on the form."""

    template_name = "core/form.html"
    success_message = _("Guardado.")

    def form_valid(self, form) -> HttpResponse:
        """Save the record with the audit entry, or show the validation error."""
        instance = form.save(commit=False)
        reason = form.cleaned_data.get("reason", "")
        try:
            audited_save(instance, self.request.user, reason)
        except ValidationError as error:
            _add_validation_errors(form, error)
            return self.form_invalid(form)
        form.save_m2m()
        self.object = instance
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


class ManagedCreateView(AuditedFormMixin, CreateView):
    """Create a record; the reason is optional (D40)."""


class ManagedUpdateView(AuditedFormMixin, UpdateView):
    """Edit a record; the form requires a reason."""


class ManagedDeleteView(ManagedViewMixin, DeleteView):
    """Ask for a reason, then delete through ``audited_delete``.

    A record that other records still use (``PROTECT``) is kept; the user gets a message
    and nothing is written to the audit log.
    """

    template_name = "core/confirm_delete.html"
    form_class = DeleteReasonForm

    def form_valid(self, form) -> HttpResponse:
        """Delete the record, or explain why it cannot be deleted."""
        try:
            audited_delete(self.object, self.request.user, form.cleaned_data["reason"])
        except ProtectedError:
            messages.error(self.request, _("Não é possível eliminar: o registo está em uso."))
            return redirect(self.get_success_url())
        messages.success(self.request, _("Eliminado."))
        return redirect(self.get_success_url())
