"""Views of ``rooms`` for Património.

Implements: docs/especificacao/02_perfis_e_dados.md – Património enters the rooms; D50 (UI
pattern), D63. Only the Património profile reaches these screens (actions ``room.edit`` and
``room_type.edit``); rooms are University-wide, so there is no Faculty scope.
"""

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from apps.core.generic import (
    ManagedCreateView,
    ManagedDeleteView,
    ManagedListView,
    ManagedUpdateView,
)

from .forms import RoomForm, RoomTypeForm
from .models import Room, RoomType


class RoomTypeMixin:
    """Settings shared by the room type screens."""

    model = RoomType
    permission_action = "room_type.edit"
    success_url = reverse_lazy("rooms:roomtype_list")


class RoomTypeListView(RoomTypeMixin, ManagedListView):
    """List the room types, including inactive ones."""

    template_name = "rooms/roomtype_list.html"
    title = _("Tipos de sala")


class RoomTypeCreateView(RoomTypeMixin, ManagedCreateView):
    """Add a room type."""

    form_class = RoomTypeForm
    title = _("Novo tipo de sala")


class RoomTypeUpdateView(RoomTypeMixin, ManagedUpdateView):
    """Edit or deactivate a room type (needs a reason)."""

    form_class = RoomTypeForm
    title = _("Editar tipo de sala")


class RoomTypeDeleteView(RoomTypeMixin, ManagedDeleteView):
    """Delete a room type that no room uses."""

    title = _("Eliminar tipo de sala")


class RoomMixin:
    """Settings shared by the room screens."""

    model = Room
    permission_action = "room.edit"
    success_url = reverse_lazy("rooms:room_list")


class RoomListView(RoomMixin, ManagedListView):
    """List the rooms with filters by type, minimum capacity and building.

    A request made by HTMX (``HX-Request`` header) gets only the results fragment (D50).
    """

    title = _("Salas")

    def get_template_names(self) -> list[str]:
        """Return the fragment for HTMX requests and the full page otherwise."""
        if self.request.headers.get("HX-Request"):
            return ["rooms/_room_results.html"]
        return ["rooms/room_list.html"]

    def get_queryset(self):
        """Apply the ``room_type``, ``min_capacity`` and ``building`` filters."""
        queryset = Room.objects.select_related("room_type")
        params = self.request.GET
        if params.get("room_type", "").isdigit():
            queryset = queryset.filter(room_type_id=int(params["room_type"]))
        if params.get("min_capacity", "").isdigit():
            queryset = queryset.filter(capacity__gte=int(params["min_capacity"]))
        if params.get("building", "").strip():
            queryset = queryset.filter(building__icontains=params["building"].strip())
        return queryset

    def get_context_data(self, **kwargs):
        """Add the filter choices and the active filter values."""
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context["room_types"] = RoomType.objects.all()
        context["selected_type"] = params.get("room_type", "")
        context["selected_capacity"] = params.get("min_capacity", "")
        context["selected_building"] = params.get("building", "")
        return context


class RoomCreateView(RoomMixin, ManagedCreateView):
    """Add a room."""

    form_class = RoomForm
    title = _("Nova sala")


class RoomUpdateView(RoomMixin, ManagedUpdateView):
    """Edit a room (needs a reason and carries the version)."""

    form_class = RoomForm
    title = _("Editar sala")


class RoomDeleteView(RoomMixin, ManagedDeleteView):
    """Delete a room."""

    title = _("Eliminar sala")
