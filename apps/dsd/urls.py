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
    path("my-sheet/", views.MySheetView.as_view(), name="my_sheet"),
    path("<int:pk>/state/", views.DsdStateView.as_view(), name="dsd_state"),
    path(
        "<int:pk>/coordinations/<int:coordination_pk>/",
        views.CoordinationOverviewView.as_view(),
        name="coordination_overview",
    ),
    path(
        "<int:pk>/coordinations/<int:coordination_pk>/load.csv",
        views.CoordinationLoadCsvView.as_view(),
        name="coordination_load_csv",
    ),
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
    path(
        "<int:pk>/teachers/<int:teacher_pk>/extra/",
        views.ExtraAcceptView.as_view(),
        name="extra_accept",
    ),
    path("extra/<int:pk>/clear/", views.ExtraClearView.as_view(), name="extra_clear"),
    path(
        "<int:pk>/teachers/<int:teacher_pk>/below-minimum/",
        views.MinimumReasonView.as_view(),
        name="minimum_reason",
    ),
    path(
        "<int:pk>/below-minimum/",
        views.MinimumReviewListView.as_view(),
        name="minimum_review_list",
    ),
    path(
        "below-minimum/<int:pk>/review/",
        views.MinimumReviewView.as_view(),
        name="minimum_review",
    ),
    path("activities/<int:pk>/edit/", views.ActivityEditView.as_view(), name="activity_edit"),
    path("activities/<int:pk>/remove/", views.ActivityRemoveView.as_view(), name="activity_remove"),
    path(
        "offerings/<int:pk>/units/<int:unit_pk>/teacher/inline/",
        views.UnitTeacherInlineView.as_view(),
        name="unit_teacher_inline",
    ),
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
