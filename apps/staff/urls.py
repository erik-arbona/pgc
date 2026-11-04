"""URLs of ``staff`` (mounted under ``/staff/``).

Implements: docs/especificacao/02_perfis_e_dados.md – PGC manager area for teachers.
"""

from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/new/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_update"),
    path("categories/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="category_delete"),
    path("positions/", views.PositionListView.as_view(), name="position_list"),
    path("positions/new/", views.PositionCreateView.as_view(), name="position_create"),
    path("positions/<int:pk>/edit/", views.PositionUpdateView.as_view(), name="position_update"),
    path("positions/<int:pk>/delete/", views.PositionDeleteView.as_view(), name="position_delete"),
]
