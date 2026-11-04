"""Views of ``core``: home page for authenticated users and the system parameters.

Implements: docs/especificacao/07_arquitetura.md – Authentication (login required).
Login and logout use Django's built-in views (see config/urls.py).
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from .forms import ParameterForm
from .generic import ManagedListView, ManagedUpdateView
from .models import Parameter


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
