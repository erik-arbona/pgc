"""URLs of ``dsd`` (mounted under ``/dsd/``).

Implements: docs/backlog_fase2.md T2.1.
"""

from django.urls import path

from . import views

app_name = "dsd"

urlpatterns = [
    path("", views.DsdListView.as_view(), name="dsd_list"),
    path("new/", views.DsdCreateView.as_view(), name="dsd_create"),
]
