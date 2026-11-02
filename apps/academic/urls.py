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
    path("coordinations/", views.CoordinationListView.as_view(), name="coordination_list"),
    path("coordinations/new/", views.CoordinationCreateView.as_view(), name="coordination_create"),
    path(
        "coordinations/<int:pk>/edit/",
        views.CoordinationUpdateView.as_view(),
        name="coordination_update",
    ),
    path(
        "coordinations/<int:pk>/delete/",
        views.CoordinationDeleteView.as_view(),
        name="coordination_delete",
    ),
    path("courses/", views.CourseListView.as_view(), name="course_list"),
    path("courses/new/", views.CourseCreateView.as_view(), name="course_create"),
    path("courses/<int:pk>/edit/", views.CourseUpdateView.as_view(), name="course_update"),
    path("courses/<int:pk>/delete/", views.CourseDeleteView.as_view(), name="course_delete"),
    path("study-plans/", views.StudyPlanListView.as_view(), name="studyplan_list"),
    path("study-plans/new/", views.StudyPlanCreateView.as_view(), name="studyplan_create"),
    path(
        "study-plans/<int:pk>/edit/", views.StudyPlanUpdateView.as_view(), name="studyplan_update"
    ),
    path(
        "study-plans/<int:pk>/delete/", views.StudyPlanDeleteView.as_view(), name="studyplan_delete"
    ),
    path("enrollments/", views.EnrollmentListView.as_view(), name="enrollment_list"),
    path("enrollments/new/", views.EnrollmentCreateView.as_view(), name="enrollment_create"),
    path("enrollments/pending/", views.EnrollmentPendingView.as_view(), name="enrollment_pending"),
    path(
        "enrollments/<int:pk>/edit/",
        views.EnrollmentUpdateView.as_view(),
        name="enrollment_update",
    ),
    path(
        "enrollments/<int:pk>/delete/",
        views.EnrollmentDeleteView.as_view(),
        name="enrollment_delete",
    ),
    path("tracks/", views.TrackListView.as_view(), name="track_list"),
    path("tracks/new/", views.TrackCreateView.as_view(), name="track_create"),
    path("tracks/<int:pk>/edit/", views.TrackUpdateView.as_view(), name="track_update"),
    path("tracks/<int:pk>/delete/", views.TrackDeleteView.as_view(), name="track_delete"),
    path("subjects/", views.SubjectListView.as_view(), name="subject_list"),
    path("subjects/new/", views.SubjectCreateView.as_view(), name="subject_create"),
    path("subjects/<int:pk>/edit/", views.SubjectUpdateView.as_view(), name="subject_update"),
    path("subjects/<int:pk>/delete/", views.SubjectDeleteView.as_view(), name="subject_delete"),
    path("class-groups/", views.ClassGroupListView.as_view(), name="classgroup_list"),
    path("class-groups/new/", views.ClassGroupCreateView.as_view(), name="classgroup_create"),
    path(
        "class-groups/<int:pk>/edit/",
        views.ClassGroupUpdateView.as_view(),
        name="classgroup_update",
    ),
    path(
        "class-groups/<int:pk>/delete/",
        views.ClassGroupDeleteView.as_view(),
        name="classgroup_delete",
    ),
    path("cross-course/", views.CrossCourseListView.as_view(), name="crosscourse_list"),
    path("cross-course/new/", views.CrossCourseCreateView.as_view(), name="crosscourse_create"),
    path(
        "cross-course/preview/",
        views.CrossCoursePreviewView.as_view(),
        name="crosscourse_preview",
    ),
    path(
        "cross-course/<int:pk>/edit/",
        views.CrossCourseUpdateView.as_view(),
        name="crosscourse_update",
    ),
    path(
        "cross-course/<int:pk>/delete/",
        views.CrossCourseDeleteView.as_view(),
        name="crosscourse_delete",
    ),
]
