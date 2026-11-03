"""URLs of ``dsd`` (mounted under ``/dsd/``).

Implements: docs/backlog_fase2.md T2.1 and T2.2.
"""

from django.urls import path

from . import views

app_name = "dsd"

urlpatterns = [
    path("", views.DsdListView.as_view(), name="dsd_list"),
    path("new/", views.DsdCreateView.as_view(), name="dsd_create"),
    path("<int:pk>/", views.DsdDetailView.as_view(), name="dsd_detail"),
    path("<int:pk>/state/", views.DsdStateView.as_view(), name="dsd_state"),
]
