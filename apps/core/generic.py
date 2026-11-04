"""Shared building blocks for the data-entry screens (list, create, edit, delete).

Implements: docs/especificacao/07_arquitetura.md – permissions checked on the server and
audit of every change; D40 (reason), D50 (UI pattern), D51 (scoped screens).
Every write goes through ``audited_save`` / ``audited_delete``; updates and deletions need a
reason. Screens work with plain forms (POST, redirect, GET) and need no JavaScript.

Two families of views: ``Managed*`` for unscoped actions and ``Scoped*`` for actions bound to
a scope (for example a Faculty), which only show and accept what the user manages.
"""

from __future__ import annotations

from operator import attrgetter

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .audit import audited_delete, audited_save
from .mixins import PermissionRequiredMixin
from .permissions import registry
from .roles import ScopeKind

PAGE_SIZE = 25
REASON_LABEL = _("Motivo")


# Usual reasons offered as a one-click choice (D59). The audit entry stores the text.
REASON_CHOICES = [
    ("", "---------"),
    ("correction", _("Correção de erro")),
    ("data_update", _("Atualização de dados")),
    ("plan_change", _("Alteração do plano de estudos")),
    ("board_decision", _("Decisão do Conselho Executivo")),
    ("created_by_mistake", _("Registo criado por engano")),
]


class ReasonFieldsMixin:
    """Add the reason fields to a form: a list of usual reasons plus optional free text (D59).

    The final reason, in ``cleaned_data["reason"]``, is the free text if only it is given, the
    preset's text if only a preset is chosen, and ``"<preset>: <text>"`` if both are. When the
    reason is required (editing or deleting, D40) at least one of them must be given.

    Call ``_setup_reason(required)`` at the end of ``__init__``. Forms that add fields after
    that call ``move_reason_last()`` to keep the two reason fields at the end.
    """

    reason_required = False

    def _setup_reason(self, required: bool) -> None:
        """Create the preset selector and relax the text field; the check is in ``clean``."""
        self.reason_required = required
        self.fields["reason_choice"] = forms.ChoiceField(
            label=REASON_LABEL, required=False, choices=REASON_CHOICES
        )
        self.fields["reason"].required = False
        self.fields["reason"].label = _("Detalhe do motivo")
        self.fields["reason"].help_text = _(
            "Obrigatório ao alterar ou eliminar: escolha um motivo ou escreva o detalhe."
        )
        self.move_reason_last()

    def move_reason_last(self) -> None:
        """Put the preset selector and the reason text at the end of the form."""
        self.fields["reason_choice"] = self.fields.pop("reason_choice")
        self.fields["reason"] = self.fields.pop("reason")

    def clean(self):
        """Combine the preset and the text into ``cleaned_data["reason"]`` and require one."""
        cleaned = super().clean()
        text = (cleaned.get("reason") or "").strip()
        choice = cleaned.get("reason_choice")
        preset = str(dict(REASON_CHOICES)[choice]) if choice else ""
        final = f"{preset}: {text}" if preset and text else (text or preset)
        cleaned["reason"] = final
        if self.reason_required and not final and "reason_choice" not in self.errors:
            self.add_error("reason", _("Indique o motivo: escolha um da lista ou escreva-o."))
        return cleaned


class ReasonModelForm(ReasonFieldsMixin, forms.ModelForm):
    """Model form with the reason fields, required when the record already exists (D40, D59)."""

    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setup_reason(required=self.instance.pk is not None)


class ScopedModelForm(ReasonModelForm):
    """Reason form whose ``scope_field`` choices are limited to the user's scopes (D51).

    Set ``scope_field`` (default ``"faculty"``) and, when the field is not the scope itself,
    ``scope_filter`` (for example ``"faculty_id__in"`` for a course field). The view passes
    ``allowed_scope_ids``.
    """

    scope_field = "faculty"
    scope_filter = "pk__in"  # how to filter the field queryset by the allowed ids

    def __init__(self, *args, allowed_scope_ids=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if allowed_scope_ids is not None and self.scope_field in self.fields:
            field = self.fields[self.scope_field]
            field.queryset = field.queryset.filter(**{self.scope_filter: allowed_scope_ids})


class DeleteReasonForm(ReasonFieldsMixin, forms.Form):
    """Confirmation form of a deletion: a reason is always required (D40, D59)."""

    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setup_reason(required=True)


class PageMixin:
    """Add the page title and the cancel link to the template context."""

    title: str = ""

    def get_context_data(self, **kwargs):
        """Add ``title`` and ``cancel_url`` to the context."""
        context = super().get_context_data(**kwargs)
        context["title"] = self.title
        context["cancel_url"] = getattr(self, "success_url", None) or "/"
        # Keep the active filters in the pagination links.
        params = self.request.GET.copy()
        params.pop("page", None)
        encoded = params.urlencode()
        context["query_string"] = f"&{encoded}" if encoded else ""
        return context


def add_validation_errors(form: forms.Form, error: ValidationError) -> None:
    """Show a ``ValidationError`` raised while saving on the form it came from."""
    if hasattr(error, "error_dict"):
        for field, messages_ in error.message_dict.items():
            form.add_error(field if field in form.fields else None, messages_)
    else:
        form.add_error(None, error.messages)


class AuditedSaveMixin:
    """Save through ``audited_save`` and report model-level errors on the form."""

    template_name = "core/form.html"
    success_message = _("Guardado.")

    def save_form(self, form):
        """Save the form's record through ``audited_save`` and return it.

        Override to save more than one record in the same transaction (see the subject
        form with its weekly hours). May raise ``ValidationError``.
        """
        instance = form.save(commit=False)
        audited_save(instance, self.request.user, form.cleaned_data.get("reason", ""))
        return instance

    def form_valid(self, form) -> HttpResponse:
        """Save the record with the audit entry, or show the validation error."""
        try:
            instance = self.save_form(form)
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        if hasattr(form, "save_m2m"):  # absent when save_form did not call form.save(commit=False)
            form.save_m2m()
        self.object = instance
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


class AuditedDeleteMixin:
    """Ask for a reason, then delete through ``audited_delete``.

    A record that other records still use (``PROTECT``) is kept; the user gets a message
    and nothing is written to the audit log.
    """

    template_name = "core/confirm_delete.html"
    form_class = DeleteReasonForm

    def delete_object(self, form) -> None:
        """Delete ``self.object`` through ``audited_delete``.

        Override to delete related rows in the same transaction with their own audit entries.
        """
        audited_delete(self.object, self.request.user, form.cleaned_data["reason"])

    def form_valid(self, form) -> HttpResponse:
        """Delete the record, or explain why it cannot be deleted."""
        try:
            self.delete_object(form)
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        except ProtectedError:
            messages.error(self.request, _("Não é possível eliminar: o registo está em uso."))
            return redirect(self.get_success_url())
        messages.success(self.request, _("Eliminado."))
        return redirect(self.get_success_url())


# --- Unscoped screens -------------------------------------------------------------------


class ManagedViewMixin(PageMixin, LoginRequiredMixin, PermissionRequiredMixin):
    """Require a session (redirect to login) and then the view's ``permission_action``."""


class ManagedListView(ManagedViewMixin, ListView):
    """Paginated list (25 per page) restricted to who holds the permission."""

    paginate_by = PAGE_SIZE


class ManagedCreateView(ManagedViewMixin, AuditedSaveMixin, CreateView):
    """Create a record; the reason is optional (D40)."""


class ManagedUpdateView(ManagedViewMixin, AuditedSaveMixin, UpdateView):
    """Edit a record; the form requires a reason."""


class ManagedDeleteView(ManagedViewMixin, AuditedDeleteMixin, DeleteView):
    """Delete a record after asking for a reason."""


# --- Scoped screens (D51) ---------------------------------------------------------------


class ScopedViewMixin(PageMixin, LoginRequiredMixin):
    """Limit a screen to the scopes (for example Faculties) the user manages.

    Set ``permission_action`` (a scoped action), ``scope_kind``, ``scope_field`` (attribute
    of the model that holds the scope id, for example ``"faculty_id"``) and
    ``scope_lookup`` (queryset filter, for example ``"faculty__in"``). A user with no scope
    for the action gets 403; anonymous users are sent to the login page.
    """

    permission_action: str = ""
    scope_kind: str = ScopeKind.FACULTY
    scope_field: str = "faculty_id"  # dotted path allowed, e.g. "course.faculty_id"
    scope_lookup: str = "faculty__in"

    def allowed_scope_ids(self) -> set[int]:
        """Return the scope ids the current user may act on."""
        return registry.scope_ids(self.request.user, self.permission_action, self.scope_kind)

    def require_scope_of(self, obj) -> None:
        """Raise ``PermissionDenied`` unless the user may act on the object's scope."""
        registry.require(
            self.request.user,
            self.permission_action,
            self.scope_kind,
            attrgetter(self.scope_field)(obj),
        )

    def dispatch(self, request, *args, **kwargs):
        """Refuse users without any scope for the action before running a handler."""
        if request.user.is_authenticated and not self.allowed_scope_ids():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class ScopedObjectMixin(ScopedViewMixin):
    """For views on one object: check the object's scope when it is loaded."""

    def get_object(self, queryset=None):
        """Return the object after checking that the user manages its scope."""
        obj = super().get_object(queryset)
        self.require_scope_of(obj)
        return obj


class ScopedFormMixin(ScopedObjectMixin, AuditedSaveMixin):
    """Forms limited to the user's scopes; the new scope is checked again on save."""

    def get_form_kwargs(self):
        """Pass the allowed scope ids to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["allowed_scope_ids"] = self.allowed_scope_ids()
        return kwargs

    def form_valid(self, form) -> HttpResponse:
        """Re-check the scope of the saved values, then save."""
        self.require_scope_of(form.instance)
        return super().form_valid(form)


class ScopedListView(ScopedViewMixin, ListView):
    """Paginated list showing only what the user manages."""

    paginate_by = PAGE_SIZE

    def get_queryset(self):
        """Filter the list to the user's scopes."""
        return super().get_queryset().filter(**{self.scope_lookup: self.allowed_scope_ids()})


class ScopedCreateView(ScopedFormMixin, CreateView):
    """Create a record in one of the user's scopes."""


class ScopedUpdateView(ScopedFormMixin, UpdateView):
    """Edit a record the user manages; the form requires a reason."""


class ScopedDeleteView(ScopedObjectMixin, AuditedDeleteMixin, DeleteView):
    """Delete a record the user manages, after asking for a reason."""
