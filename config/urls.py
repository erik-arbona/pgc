"""Root URL configuration.

Implements: docs/especificacao/07_arquitetura.md – web application.
Only the Django admin is routed for now; feature apps add their URLs later.
"""

from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
