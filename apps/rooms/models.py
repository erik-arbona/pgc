"""Models of ``rooms``: room types and rooms.

Implements: docs/especificacao/02_perfis_e_dados.md – Património enters the rooms of the
University (location, name when it has one, type and capacity); 03_requisitos_funcionais.md –
block 8; D07, D63. Património keeps them up to date and does not assign rooms.
All writes should go through ``apps.core.audit.audited_save`` (CLAUDE.md rule 7).
"""

from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.core.models import VersionedModel


class RoomType(models.Model):
    """A kind of room (amphitheatre, laboratory...), configured by Património.

    The specification does not list the types, so none is loaded by code (D63).
    """

    code = models.CharField(
        _("código"), max_length=20, unique=True, help_text=_("Short unique code, e.g. 'LAB'.")
    )
    name = models.CharField(
        _("nome"), max_length=100, unique=True, help_text=_("Name of the room type.")
    )
    is_active = models.BooleanField(
        _("ativo"),
        default=True,
        help_text=_("Inactive types are not offered for new rooms; existing rooms keep them."),
    )
    position = models.PositiveSmallIntegerField(
        _("posição"), default=100, help_text=_("Display order; lower values come first.")
    )

    class Meta:
        verbose_name = _("tipo de sala")
        verbose_name_plural = _("tipos de sala")
        ordering = ["position", "code"]

    def __str__(self) -> str:
        return self.name


class Room(VersionedModel):
    """A room of the University, for example Edifício 9, sala 101, with 27 places.

    Rooms are University-wide (no Faculty). The version field is the optimistic lock: several
    people may edit rooms (CLAUDE.md).
    """

    building = models.CharField(
        _("edifício"), max_length=100, help_text=_("Building, e.g. 'Edifício 9'.")
    )
    number = models.CharField(
        _("número"),
        max_length=30,
        help_text=_("Room number or code inside the building; text, e.g. '101' or 'A12'."),
    )
    name = models.CharField(
        _("nome"),
        max_length=150,
        blank=True,
        help_text=_("Name, when the room has one (an amphitheatre or laboratory)."),
    )
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.PROTECT,  # a type in use cannot be removed
        related_name="rooms",
        verbose_name=_("tipo"),
        help_text=_("Type of room."),
    )
    capacity = models.PositiveSmallIntegerField(
        _("capacidade"), help_text=_("Number of places (students) the room holds.")
    )

    class Meta:
        verbose_name = _("sala")
        verbose_name_plural = _("salas")
        ordering = ["building", "number"]
        constraints = [
            # A room is identified by its building and number, whatever the letter case.
            models.UniqueConstraint(
                Lower("building"), Lower("number"), name="unique_room_location"
            ),
            models.CheckConstraint(
                condition=models.Q(capacity__gt=0), name="room_capacity_positive"
            ),
        ]

    def __str__(self) -> str:
        label = f"{self.building}, {self.number}"
        return f"{label} – {self.name}" if self.name else label
