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
    path("faculties/", views.FacultyListView.as_view(), name="faculty_list"),
    path("faculties/new/", views.FacultyCreateView.as_view(), name="faculty_create"),
    path("faculties/<int:pk>/edit/", views.FacultyUpdateView.as_view(), name="faculty_update"),
    path("faculties/<int:pk>/delete/", views.FacultyDeleteView.as_view(), name="faculty_delete"),
    path("academic-years/", views.AcademicYearListView.as_view(), name="academicyear_list"),
    path("academic-years/new/", views.AcademicYearCreateView.as_view(), name="academicyear_create"),
    path(
        "academic-years/<int:pk>/edit/",
        views.AcademicYearUpdateView.as_view(),
        name="academicyear_update",
    ),
    path(
        "academic-years/<int:pk>/delete/",
        views.AcademicYearDeleteView.as_view(),
        name="academicyear_delete",
    ),
]
