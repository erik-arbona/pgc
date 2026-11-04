"""URLs of ``dsd`` (mounted under ``/dsd/``).

Implements: docs/backlog_fase2.md T2.1-T2.3.
"""

from django.urls import path

from . import views

app_name = "dsd"

urlpatterns = [
    path("", views.DsdListView.as_view(), name="dsd_list"),
    path("new/", views.DsdCreateView.as_view(), name="dsd_create"),
    path("<int:pk>/", views.DsdDetailView.as_view(), name="dsd_detail"),
    path("<int:pk>/state/", views.DsdStateView.as_view(), name="dsd_state"),
    path("<int:pk>/offerings/", views.OfferingListView.as_view(), name="offering_list"),
    path(
        "offerings/<int:pk>/lead-teacher/",
        views.OfferingLeadTeacherView.as_view(),
        name="offering_lead_teacher",
    ),
    path(
        "<int:pk>/offerings/generate/",
        views.OfferingGenerateView.as_view(),
        name="offering_generate",
    ),
]
