"""Root URL configuration.

Implements: docs/especificacao/07_arquitetura.md – web application and authentication.
Feature apps add their URLs later.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core.views import HomeView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("core/", include("apps.core.urls")),
    path("academic/", include("apps.academic.urls")),
    path("staff/", include("apps.staff.urls")),
    path("rooms/", include("apps.rooms.urls")),
    path("admin/", admin.site.urls),
]
