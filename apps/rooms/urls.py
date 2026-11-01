"""URLs of ``rooms`` (mounted under ``/rooms/``).

Implements: D63 – Património area for rooms.
"""

from django.urls import path

from . import views

app_name = "rooms"

urlpatterns = [
    path("rooms/", views.RoomListView.as_view(), name="room_list"),
    path("rooms/new/", views.RoomCreateView.as_view(), name="room_create"),
    path("rooms/<int:pk>/edit/", views.RoomUpdateView.as_view(), name="room_update"),
    path("rooms/<int:pk>/delete/", views.RoomDeleteView.as_view(), name="room_delete"),
    path("types/", views.RoomTypeListView.as_view(), name="roomtype_list"),
    path("types/new/", views.RoomTypeCreateView.as_view(), name="roomtype_create"),
    path("types/<int:pk>/edit/", views.RoomTypeUpdateView.as_view(), name="roomtype_update"),
    path("types/<int:pk>/delete/", views.RoomTypeDeleteView.as_view(), name="roomtype_delete"),
]
