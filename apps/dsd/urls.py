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
    path("offerings/<int:pk>/", views.OfferingDetailView.as_view(), name="offering_detail"),
    path(
        "offerings/<int:pk>/groups/<int:link_pk>/<int:type_pk>/",
        views.GroupCountView.as_view(),
        name="offering_groups",
    ),
    path("offerings/<int:pk>/merge/", views.OfferingMergeView.as_view(), name="offering_merge"),
    path(
        "offerings/<int:pk>/units/<int:unit_pk>/separate/<int:member_pk>/",
        views.OfferingSeparateView.as_view(),
        name="offering_separate",
    ),
    path(
        "offerings/<int:pk>/units/<int:unit_pk>/room/",
        views.UnitRoomView.as_view(),
        name="unit_room",
    ),
    path(
        "offerings/<int:pk>/units/<int:unit_pk>/teacher/",
        views.UnitTeacherView.as_view(),
        name="unit_teacher",
    ),
    path(
        "<int:pk>/teachers/<int:teacher_pk>/",
        views.TeacherSheetView.as_view(),
        name="teacher_sheet",
    ),
    path(
        "<int:pk>/teachers/<int:teacher_pk>/activities/new/<int:number>/",
        views.ActivityAddView.as_view(),
        name="activity_add",
    ),
    path("activities/<int:pk>/edit/", views.ActivityEditView.as_view(), name="activity_edit"),
    path("activities/<int:pk>/remove/", views.ActivityRemoveView.as_view(), name="activity_remove"),
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
