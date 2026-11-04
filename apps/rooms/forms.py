"""Forms of ``rooms`` for Património.

Implements: docs/especificacao/02_perfis_e_dados.md – Património enters the rooms; D40, D63.
Every form that edits an existing record asks for a reason; the room form also carries the
version the user saw (optimistic lock).
"""

from django import forms
from django.forms.models import construct_instance
from django.utils.translation import gettext_lazy as _

from apps.core.generic import ReasonModelForm

from .models import Room, RoomType


class RoomTypeForm(ReasonModelForm):
    """Create or edit a room type. Unchecking ``is_active`` deactivates it."""

    class Meta:
        model = RoomType
        fields = ["code", "name", "position", "is_active"]


class RoomForm(ReasonModelForm):
    """Create or edit a room.

    Inactive room types are not offered, except the one the room already has. The location
    (building and number) is unique ignoring case, checked here so that the message is in
    Portuguese. The hidden ``version`` is the version the user saw: saving with an older one
    means someone else changed the room first and is refused (D63).
    """

    capacity = forms.IntegerField(label=_("Capacidade"), min_value=1)

    class Meta:
        model = Room
        fields = ["building", "number", "name", "room_type", "capacity", "version"]
        widgets = {"version": forms.HiddenInput()}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        keep = [self.instance.room_type_id] if self.instance.pk else []
        types = self.fields["room_type"].queryset
        self.fields["room_type"].queryset = types.filter(is_active=True) | types.filter(pk__in=keep)
        # The lock only works if an edit carries the version; a new room starts at 1.
        self.fields["version"].required = self.instance.pk is not None

    def clean(self):
        """Refuse a second room with the same building and number, ignoring case."""
        cleaned = super().clean()
        building, number = cleaned.get("building"), cleaned.get("number")
        if building and number:
            same = Room.objects.filter(building__iexact=building, number__iexact=number)
            if same.exclude(pk=self.instance.pk).exists():
                self.add_error(None, _("Já existe uma sala neste edifício com este número."))
        return cleaned

    def _post_clean(self) -> None:
        """Build the instance but skip the model's own constraint messages (shown in English)."""
        self.instance = construct_instance(
            self, self.instance, self._meta.fields, self._meta.exclude
        )
