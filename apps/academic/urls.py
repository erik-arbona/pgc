"""URLs of ``academic`` (mounted under ``/academic/``).

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1, PGC manager area.
"""

from django.urls import path

from . import views

app_name = "academic"

urlpatterns = [
    path("class-types/", views.ClassTypeListView.as_view(), name="classtype_list"),
    path("class-types/new/", views.ClassTypeCreateView.as_view(), name="classtype_create"),
    path(
        "class-types/<int:pk>/edit/",
        views.ClassTypeUpdateView.as_view(),
        name="classtype_update",
    ),
    path(
        "class-types/<int:pk>/delete/",
        views.ClassTypeDeleteView.as_view(),
        name="classtype_delete",
    ),
]
