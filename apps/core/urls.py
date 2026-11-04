"""URLs of ``core`` (mounted under ``/core/``).

Implements: D60 – PGC manager area for system parameters.
"""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("parameters/", views.ParameterListView.as_view(), name="parameter_list"),
    path(
        "parameters/<int:pk>/edit/",
        views.ParameterUpdateView.as_view(),
        name="parameter_update",
    ),
    path("accounts/", views.AccountListView.as_view(), name="account_list"),
    path("accounts/new/", views.AccountCreateView.as_view(), name="account_create"),
    path("accounts/<int:pk>/edit/", views.AccountUpdateView.as_view(), name="account_update"),
    path(
        "accounts/<int:pk>/deactivate/",
        views.AccountDeactivateView.as_view(),
        name="account_deactivate",
    ),
    path(
        "accounts/<int:pk>/activate/",
        views.AccountActivateView.as_view(),
        name="account_activate",
    ),
]
