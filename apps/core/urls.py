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
]
