"""Views of ``core``: home page for authenticated users and the system parameters.

Implements: docs/especificacao/07_arquitetura.md – Authentication (login required).
Login and logout use Django's built-in views (see config/urls.py).
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from .accounts import (
    assign_role,
    can_manage_account,
    can_revoke_role,
    create_account,
    grantable_scope_options,
    revoke_role,
    set_active,
    update_account,
    visible_accounts,
)
from .forms import AccountCreateForm, AccountRoleForm, AccountUpdateForm, ParameterForm
from .generic import (
    PAGE_SIZE,
    DeleteReasonForm,
    ManagedListView,
    ManagedUpdateView,
    ScopedViewMixin,
    add_validation_errors,
)
from .models import Parameter, RoleAssignment
from .scopes import scope_label


class HomeView(LoginRequiredMixin, TemplateView):
    """Landing page after login; anonymous visitors are redirected to the login page."""

    template_name = "core/home.html"


class ParameterMixin:
    """Settings shared by the parameter screens (PGC manager, University-wide, D60)."""

    model = Parameter
    permission_action = "parameter.edit"
    success_url = reverse_lazy("core:parameter_list")


class ParameterListView(ParameterMixin, ManagedListView):
    """List the system parameters with their current value."""

    template_name = "core/parameter_list.html"
    title = _("Parâmetros")


class ParameterUpdateView(ParameterMixin, ManagedUpdateView):
    """Change the value of a parameter (needs a reason)."""

    form_class = ParameterForm
    title = _("Editar parâmetro")


class AccountMixin:
    """Settings shared by the account screens: PGC manager, limited to their Faculties (D62)."""

    permission_action = "account.edit"
    success_url = reverse_lazy("core:account_list")


class AccountListView(AccountMixin, ScopedViewMixin, ListView):
    """List the accounts a manager can see; each row says whether it can be managed."""

    template_name = "core/account_list.html"
    title = _("Contas")
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        """Return the accounts inside the manager's Faculties and the ones without roles."""
        return visible_accounts(self.request.user)

    def get_context_data(self, **kwargs):
        """Mark each account as manageable or read-only, and list its roles."""
        context = super().get_context_data(**kwargs)
        accounts = list(context["object_list"])
        for account in accounts:
            account.can_manage = can_manage_account(self.request.user, account)
            account.roles = [
                f"{r.get_profile_display()} – {scope_label(r.scope_kind, r.scope_id)}"
                for r in account.role_assignments.all()
            ]
        context["object_list"] = accounts
        return context


class AccountCreateView(AccountMixin, ScopedViewMixin, FormView):
    """Create an account; the manager then adds its roles on the account page."""

    template_name = "core/form.html"
    form_class = AccountCreateForm
    title = _("Nova conta")

    def form_valid(self, form):
        """Create the account through the audited service and open its page."""
        data = form.cleaned_data
        try:
            user = create_account(
                self.request.user,
                username=data["username"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                email=data["email"],
                reason=data.get("reason", ""),
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Conta criada. A conta não tem palavra-passe."))
        return redirect(reverse("core:account_update", kwargs={"pk": user.pk}))


class AccountObjectMixin:
    """Load the account of the URL and refuse it unless the manager may manage it (403)."""

    def _load_account(self):
        """Return the account, or raise ``PermissionDenied`` if it is out of reach."""
        user = get_object_or_404(get_user_model(), pk=self.kwargs["pk"])
        if not can_manage_account(self.request.user, user):
            raise PermissionDenied
        return user

    def get(self, request, *args, **kwargs):
        """Show the page for a manageable account."""
        self.account = self._load_account()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Accept the form for a manageable account."""
        self.account = self._load_account()
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Add the account and its roles to the page."""
        context = super().get_context_data(**kwargs)
        context["account"] = self.account
        context["roles"] = [
            {
                "pk": r.pk,
                "profile": r.get_profile_display(),
                "scope": scope_label(r.scope_kind, r.scope_id),
                "can_revoke": can_revoke_role(self.request.user, r),
            }
            for r in self.account.role_assignments.all()
        ]
        return context


class AccountUpdateView(AccountMixin, ScopedViewMixin, AccountObjectMixin, FormView):
    """Edit the names and e-mail of an account (needs a reason); the username never changes."""

    template_name = "core/account_form.html"
    form_class = AccountUpdateForm
    title = _("Editar conta")

    def get_context_data(self, **kwargs):
        """Add the form that adds a role, with the scopes the manager can grant."""
        context = super().get_context_data(**kwargs)
        context["role_form"] = AccountRoleForm(options=grantable_scope_options(self.request.user))
        return context

    def get_initial(self):
        """Start from the account's current values."""
        user = self.account
        return {"first_name": user.first_name, "last_name": user.last_name, "email": user.email}

    def form_valid(self, form):
        """Save through the audited service."""
        data = form.cleaned_data
        try:
            update_account(
                self.request.user,
                self.account,
                first_name=data["first_name"],
                last_name=data["last_name"],
                email=data["email"],
                reason=data["reason"],
            )
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Guardado."))
        return redirect(self.get_success_url())


class AccountActiveView(AccountMixin, ScopedViewMixin, AccountObjectMixin, FormView):
    """Activate or deactivate an account after asking for a reason (D62)."""

    template_name = "core/account_active.html"
    form_class = DeleteReasonForm
    active = False

    def form_valid(self, form):
        """Change the state through the audited service."""
        try:
            set_active(self.request.user, self.account, self.active, form.cleaned_data["reason"])
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Guardado."))
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        """Tell the template which action it is confirming."""
        context = super().get_context_data(**kwargs)
        context["active"] = self.active
        context["title"] = _("Ativar conta") if self.active else _("Desativar conta")
        return context


class AccountDeactivateView(AccountActiveView):
    """Deactivate an account: it can no longer log in, and its session ends."""

    active = False


class AccountActivateView(AccountActiveView):
    """Reactivate an account."""

    active = True


class AccountRoleAddView(AccountMixin, ScopedViewMixin, AccountObjectMixin, View):
    """Add a role to an account (POST only); the service checks the manager's authority."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        """Create the role, or show why not.

        A scope outside the manager's Faculties raises ``PermissionDenied`` (403); an invalid or
        non-existing value only shows a message on the account page.
        """
        self.account = self._load_account()
        back = redirect(reverse("core:account_update", kwargs={"pk": self.account.pk}))
        form = AccountRoleForm(request.POST, options=grantable_scope_options(request.user))
        if not form.is_valid():
            messages.error(request, _("Escolha um perfil e um âmbito válidos."))
            return back
        kind, scope_id = form.cleaned_data["scope"]
        try:
            assign_role(
                request.user,
                self.account,
                form.cleaned_data["profile"],
                kind,
                scope_id,
                form.cleaned_data["reason"],
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return back
        messages.success(request, _("Perfil atribuído."))
        return back


class AccountRoleScopesView(AccountMixin, ScopedViewMixin, AccountObjectMixin, View):
    """HTMX fragment: the scope options that fit a profile (D50)."""

    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        """Return the ``<option>`` list for the chosen profile."""
        self.account = self._load_account()
        options = grantable_scope_options(request.user, request.GET.get("profile") or None)
        return render(request, "core/_scope_options.html", {"options": options})


class AccountRoleRemoveView(AccountMixin, ScopedViewMixin, FormView):
    """Confirm and remove a role, asking for a reason (D62)."""

    template_name = "core/account_role_remove.html"
    form_class = DeleteReasonForm
    title = _("Retirar perfil")

    def _load_role(self):
        """Return the role, or raise ``PermissionDenied`` if the manager may not remove it."""
        role = get_object_or_404(
            RoleAssignment.objects.select_related("user"), pk=self.kwargs["pk"]
        )
        if not can_revoke_role(self.request.user, role):
            raise PermissionDenied
        return role

    def get(self, request, *args, **kwargs):
        """Show the confirmation page for a role the manager may remove."""
        self.role = self._load_role()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Remove the role after checking the authority again."""
        self.role = self._load_role()
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Add the role and where it belongs to the page."""
        context = super().get_context_data(**kwargs)
        context["role"] = self.role
        context["scope"] = scope_label(self.role.scope_kind, self.role.scope_id)
        context["cancel_url"] = reverse("core:account_update", kwargs={"pk": self.role.user_id})
        return context

    def form_valid(self, form):
        """Remove the role through the audited service."""
        holder_id = self.role.user_id
        try:
            revoke_role(self.request.user, self.role, form.cleaned_data["reason"])
        except ValidationError as error:
            add_validation_errors(form, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Perfil retirado."))
        return redirect(reverse("core:account_update", kwargs={"pk": holder_id}))
