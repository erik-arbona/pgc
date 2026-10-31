"""Views of ``core``: home page for authenticated users.

Implements: docs/especificacao/07_arquitetura.md – Authentication (login required).
Login and logout use Django's built-in views (see config/urls.py).
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class HomeView(LoginRequiredMixin, TemplateView):
    """Landing page after login; anonymous visitors are redirected to the login page."""

    template_name = "core/home.html"
