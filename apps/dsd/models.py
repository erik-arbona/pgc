"""Models of the DSD: the DSD, its semesters, their states, the offerings and the units.

Implements: docs/especificacao/04_modelo_de_dados.md – DSD; docs/backlog_fase2.md T2.1.
See D43: a single DSD per academic year for the whole University, created only by the PGC
manager. The state of each semester per coordination (open, closed) comes with T2.2.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Subject,
)
from apps.core.models import VersionedModel
from apps.rooms.models import RoomType
from apps.staff.models import Teacher

from .guard import GuardedDsdWrites
from .tender_rules import TenderState


class Dsd(models.Model):
    """The DSD (teaching service distribution) of one academic year.

    There is exactly one for the whole University (D43). It always has two semesters, created
    together with it by ``apps.dsd.services.create_dsd``.
    """

    academic_year = models.OneToOneField(
        AcademicYear,
        on_delete=models.PROTECT,  # a year that has a DSD cannot be deleted
        related_name="dsd",
        verbose_name=_("ano letivo"),
        help_text=_("Academic year of this DSD; a single DSD exists per academic year (D43)."),
    )

    class Meta:
        verbose_name = _("DSD")
        verbose_name_plural = _("DSD")
        ordering = ["-academic_year__start_year"]

    def __str__(self) -> str:
        return f"DSD {self.academic_year.label}"


class DsdSemester(models.Model):
    """One of the two semesters of a DSD.

    It is the target of the offerings (T2.3) and, from T2.2, of the open/closed state of each
    coordination.
    """

    dsd = models.ForeignKey(
        Dsd,
        on_delete=models.CASCADE,  # the semesters only exist inside their DSD
        related_name="semesters",
        verbose_name=_("DSD"),
        help_text=_("DSD the semester belongs to."),
    )
    number = models.PositiveSmallIntegerField(
        _("semestre"), help_text=_("Semester number: 1 or 2.")
    )

    class Meta:
        verbose_name = _("semestre do DSD")
        verbose_name_plural = _("semestres do DSD")
        ordering = ["dsd", "number"]
        constraints = [
            # Each semester exists once in a DSD.
            models.UniqueConstraint(fields=["dsd", "number"], name="unique_semester_per_dsd"),
            # The DSD only has the 1st and the 2nd semester.
            models.CheckConstraint(
                condition=models.Q(number__in=[1, 2]), name="dsd_semester_number_is_1_or_2"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.dsd} – S{self.number}"


class CoordinationSemester(VersionedModel):
    """The state of one semester of the DSD for one coordination (T2.2, D43).

    A missing row means "not opened yet": a coordination created later starts that way. The
    allowed moves are in ``lifecycle_rules``; who, when and why come from the audit entries.
    """

    class Status(models.TextChoices):
        """The two stored states; "not opened" is the absence of the row."""

        OPEN = "open", _("aberto")
        CLOSED = "closed", _("fechado")

    dsd_semester = models.ForeignKey(
        DsdSemester,
        on_delete=models.PROTECT,  # never lose the state of a semester that has one
        related_name="coordination_states",
        verbose_name=_("semestre do DSD"),
        help_text=_("Semester of the DSD the state refers to."),
    )
    coordination = models.ForeignKey(
        Coordination,
        on_delete=models.PROTECT,  # a coordination with a state cannot be deleted
        related_name="semester_states",
        verbose_name=_("coordenação"),
        help_text=_("Coordination the state refers to."),
    )
    status = models.CharField(
        _("estado"),
        max_length=10,
        choices=Status.choices,
        help_text=_("Open: the coordination distributes; closed: read-only (D43)."),
    )

    class Meta:
        verbose_name = _("estado do semestre por coordenação")
        verbose_name_plural = _("estados dos semestres por coordenação")
        ordering = ["dsd_semester", "coordination"]
        constraints = [
            # One state per semester and coordination, also when two managers open at once.
            models.UniqueConstraint(
                fields=["dsd_semester", "coordination"], name="unique_state_per_semester_cell"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.dsd_semester} – {self.coordination} – {self.status}"


class Offering(GuardedDsdWrites, VersionedModel):
    """A subject taught in a semester of a DSD (T2.3, D48, D49).

    There is one per semester and subject. The coordination that owns it is the subject's, so
    the write guard checks the cell ``(semester, subject.coordination)``. The turmas that take it
    are in ``OfferingClassGroup``; the teaching units (T3.1) and the assignments (T5.1) hang
    from it. ``lead_teacher`` (the regente) is set by T2.3b.
    """

    dsd_semester = models.ForeignKey(
        DsdSemester,
        on_delete=models.PROTECT,  # an offering is history of the DSD, never lost with it
        related_name="offerings",
        verbose_name=_("semestre do DSD"),
        help_text=_("Semester of the DSD in which the subject is taught."),
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,  # a subject with offerings cannot be deleted
        related_name="offerings",
        verbose_name=_("disciplina"),
        help_text=_("Subject taught; its coordination owns the offering (D69)."),
    )
    lead_teacher = models.ForeignKey(
        Teacher,
        null=True,
        blank=True,
        on_delete=models.PROTECT,  # a teacher who is regente cannot be deleted
        related_name="led_offerings",
        verbose_name=_("regente"),
        help_text=_("Teacher who leads the subject; one of the subject's coordination."),
    )

    class Meta:
        verbose_name = _("oferta no semestre")
        verbose_name_plural = _("ofertas no semestre")
        ordering = ["dsd_semester", "subject__curricular_year", "subject__name"]
        constraints = [
            # A subject is offered once per semester of a DSD, also when two managers
            # generate at the same time.
            models.UniqueConstraint(
                fields=["dsd_semester", "subject"], name="unique_offering_per_semester"
            ),
        ]

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell of this offering: its semester and the subject's coordination."""
        return self.dsd_semester_id, self.subject.coordination_id

    def clean(self) -> None:
        """Check that the subject is taught in the semester of the offering.

        Raises:
            ValidationError: if the subject's semester is not the semester number.
        """
        if self.subject.semester != self.dsd_semester.number:
            raise ValidationError(
                {"subject": _("A disciplina é lecionada noutro semestre do plano.")}
            )

    def save(self, *args, **kwargs) -> None:
        """Validate the semester before saving, so no path can create a wrong offering."""
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.dsd_semester} – {self.subject}"


class OfferingClassGroup(GuardedDsdWrites, models.Model):
    """A turma that takes an offering: a snapshot taken when the offering is generated.

    It is stored, not derived, because a turma that ends (D49) must keep the history of the
    offerings it had in earlier DSDs.
    """

    offering = models.ForeignKey(
        Offering,
        on_delete=models.CASCADE,  # the links only exist inside their offering
        related_name="class_group_links",
        verbose_name=_("oferta"),
        help_text=_("Offering the turma takes."),
    )
    class_group = models.ForeignKey(
        ClassGroup,
        on_delete=models.PROTECT,  # a turma with offerings cannot be deleted (D54)
        related_name="offering_links",
        verbose_name=_("turma"),
        help_text=_("Turma that takes the subject in that semester."),
    )

    class Meta:
        verbose_name = _("turma da oferta")
        verbose_name_plural = _("turmas da oferta")
        ordering = ["offering", "class_group"]
        constraints = [
            # A turma appears once in an offering.
            models.UniqueConstraint(
                fields=["offering", "class_group"], name="unique_class_group_per_offering"
            ),
        ]

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell of the offering the link belongs to."""
        return self.offering.dsd_cell()

    def __str__(self) -> str:
        return f"{self.offering} – {self.class_group}"


class TeachingUnit(GuardedDsdWrites, VersionedModel):
    """A teaching unit: an offering x a class type, taught to an audience (T3.1, D19, D70).

    The audience is a set of ``TeachingUnitMember`` rows, each a turma of the offering. By
    default there is one unit per turma and class type; merges (T3.3, T3.4) and groups (T3.2)
    change the audience later without changing this model. The weekly hours are not stored: they
    are read from the subject's load for the class type when the hours are calculated (D70). The
    teacher assignments (T5.1) hang from the unit. Saving it bumps ``version``, so any change of
    the audience made through the unit is protected by the optimistic lock (D54).
    """

    offering = models.ForeignKey(
        Offering,
        on_delete=models.PROTECT,  # a unit is history of the DSD, never lost with its offering
        related_name="teaching_units",
        verbose_name=_("oferta"),
        help_text=_("Offering the unit belongs to; its hours count under it."),
    )
    class_type = models.ForeignKey(
        ClassType,
        on_delete=models.PROTECT,  # a class type in use cannot be removed
        related_name="teaching_units",
        verbose_name=_("tipo de aula"),
        help_text=_("Type of class taught in this unit."),
    )
    teacher = models.ForeignKey(
        Teacher,
        null=True,
        blank=True,
        on_delete=models.PROTECT,  # a teacher with units cannot be deleted (T0.5)
        related_name="teaching_units",
        verbose_name=_("docente"),
        help_text=_("The teacher of the unit: one per unit, no sharing (D19, D94)."),
    )
    room_type = models.ForeignKey(
        RoomType,
        null=True,
        blank=True,
        on_delete=models.PROTECT,  # a room type in use cannot be removed
        related_name="requesting_units",
        verbose_name=_("tipo de sala pedido"),
        help_text=_("Type of room the coordinator asks for; empty means any (D91)."),
    )
    room_capacity = models.PositiveSmallIntegerField(
        _("capacidade de sala pedida"),
        null=True,
        blank=True,
        help_text=_("Places of the room the coordinator asks for. It is a request, not a booking."),
    )

    class Meta:
        verbose_name = _("unidade letiva")
        verbose_name_plural = _("unidades letivas")
        ordering = ["offering", "class_type__position", "pk"]
        constraints = [
            # A room request has a positive number of places, or none.
            models.CheckConstraint(
                condition=models.Q(room_capacity__isnull=True) | models.Q(room_capacity__gt=0),
                name="unit_room_capacity_positive",
            ),
        ]

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell of the offering the unit belongs to."""
        return self.offering.dsd_cell()

    def __str__(self) -> str:
        return f"{self.offering} – {self.class_type.code}"


class SubGroup(GuardedDsdWrites, models.Model):
    """One of the N groups into which a turma is divided for a class type (T3.2, D19).

    It belongs to a turma of an offering and to a class type; ``number`` runs from 1. It has no
    stored label: the page shows "turma – code + number" (for example "A – P2"). Its size is not
    stored: the groups of a turma share the turma's size (Q6, D90). Each group is attended by a
    teaching unit, whose audience can also hold groups of other turmas once they are merged.
    """

    class_group_link = models.ForeignKey(
        OfferingClassGroup,
        on_delete=models.PROTECT,  # a turma with groups cannot be removed from the offering
        related_name="subgroups",
        verbose_name=_("turma da oferta"),
        help_text=_("Turma of the offering the group belongs to."),
    )
    class_type = models.ForeignKey(
        ClassType,
        on_delete=models.PROTECT,  # a class type in use cannot be removed
        related_name="subgroups",
        verbose_name=_("tipo de aula"),
        help_text=_("Class type the turma is divided for."),
    )
    number = models.PositiveSmallIntegerField(
        _("número"), help_text=_("Number of the group inside the turma and class type, from 1.")
    )

    class Meta:
        verbose_name = _("grupo")
        verbose_name_plural = _("grupos")
        ordering = ["class_group_link", "class_type", "number"]
        constraints = [
            # A group number exists once per turma and class type.
            models.UniqueConstraint(
                fields=["class_group_link", "class_type", "number"], name="unique_subgroup_number"
            ),
            # Groups are numbered from 1.
            models.CheckConstraint(
                condition=models.Q(number__gte=1), name="subgroup_number_from_1"
            ),
        ]

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell of the offering the group belongs to."""
        return self.class_group_link.dsd_cell()

    @property
    def label(self) -> str:
        """Return the computed name, for example ``A – P2``."""
        return f"{self.class_group_link.class_group} – {self.class_type.code}{self.number}"

    def __str__(self) -> str:
        return self.label


class TeachingUnitMember(GuardedDsdWrites, models.Model):
    """A turma, or a group, that attends a teaching unit (T3.1, T3.2).

    Exactly one of ``class_group_link`` (a whole turma) and ``subgroup`` (a group) is set. The
    first points at the offering link (not at the turma) so that a merge across courses (T3.4)
    can hold links of another offering. ``class_type`` repeats the unit's, only to let the
    database guarantee that a turma attends each class type once as a whole turma.
    """

    unit = models.ForeignKey(
        TeachingUnit,
        on_delete=models.CASCADE,  # the members only exist inside their unit
        related_name="members",
        verbose_name=_("unidade letiva"),
        help_text=_("Unit that is attended."),
    )
    class_group_link = models.ForeignKey(
        OfferingClassGroup,
        null=True,
        blank=True,
        on_delete=models.PROTECT,  # a link with units cannot be deleted
        related_name="unit_memberships",
        verbose_name=_("turma da oferta"),
        help_text=_("The whole turma of the offering that attends the unit."),
    )
    subgroup = models.ForeignKey(
        SubGroup,
        null=True,
        blank=True,
        on_delete=models.PROTECT,  # a group with a unit cannot be deleted
        related_name="unit_memberships",
        verbose_name=_("grupo"),
        help_text=_("The group that attends the unit; it may belong to another turma."),
    )
    class_type = models.ForeignKey(
        ClassType,
        on_delete=models.PROTECT,  # a class type in use cannot be removed
        related_name="unit_memberships",
        verbose_name=_("tipo de aula"),
        help_text=_("Copy of the unit's class type; it must be the same."),
    )

    class Meta:
        verbose_name = _("público da unidade letiva")
        verbose_name_plural = _("público das unidades letivas")
        ordering = ["unit", "class_group_link", "subgroup"]
        constraints = [
            # A turma attends each class type once as a whole turma: the idempotency key of the
            # generation and the rule that merges (T3.3) will rely on.
            models.UniqueConstraint(
                fields=["class_group_link", "class_type"],
                name="one_whole_unit_per_turma_and_type",
            ),
            # A group belongs to one unit only.
            models.UniqueConstraint(fields=["subgroup"], name="one_unit_per_subgroup"),
            # A member is a whole turma or a group, never both and never neither.
            models.CheckConstraint(
                condition=(
                    models.Q(class_group_link__isnull=False, subgroup__isnull=True)
                    | models.Q(class_group_link__isnull=True, subgroup__isnull=False)
                ),
                name="member_is_a_turma_or_a_group",
            ),
        ]

    @property
    def turma_link(self) -> OfferingClassGroup:
        """Return the turma link the member belongs to: the whole turma or the group's turma."""
        return self.class_group_link or self.subgroup.class_group_link

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell of the unit the member belongs to."""
        return self.unit.dsd_cell()

    def clean(self) -> None:
        """Check the class type is the unit's and the member is a turma or a group.

        Raises:
            ValidationError: if the class type differs from the unit's (or the group's), or if
                both or neither of the turma and the group are given.
        """
        if self.class_type_id != self.unit.class_type_id or (
            self.subgroup_id and self.subgroup.class_type_id != self.class_type_id
        ):
            raise ValidationError(
                {"class_type": _("O tipo de aula tem de ser o da unidade letiva.")}
            )
        if (self.class_group_link_id is None) == (self.subgroup_id is None):
            raise ValidationError(_("Indique uma turma inteira ou um grupo, não os dois."))

    def save(self, *args, **kwargs) -> None:
        """Validate the member before saving."""
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.unit} – {self.subgroup or self.class_group_link.class_group}"


class OtherActivity(GuardedDsdWrites, VersionedModel):
    """An activity of the non-teaching component of a teacher in a semester (T5.3, D15, D95).

    The coordinator enters, case by case, the type (teaching complements, research, management
    and services), a description and the weekly hours. The hours add to the general total of the
    teacher and never count towards the annual range, which validates the teaching hours only.
    The coordination is that of the teacher when the activity was entered and defines the cell
    (semester x coordination) whose state decides who may write it (D86).
    """

    class Kind(models.TextChoices):
        """The three kinds of non-teaching activity of the DSD."""

        TEACHING_COMPLEMENTS = "teaching_complements", _("Complementos de ensino")
        RESEARCH = "research", _("Investigação")
        MANAGEMENT = "management", _("Gestão e serviços")

    dsd_semester = models.ForeignKey(
        DsdSemester,
        on_delete=models.PROTECT,  # a semester with activities cannot be removed
        related_name="other_activities",
        verbose_name=_("semestre do DSD"),
        help_text=_("Semester of the DSD the activity is carried out in."),
    )
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.PROTECT,  # a teacher with activities cannot be deleted (T0.5)
        related_name="other_activities",
        verbose_name=_("docente"),
        help_text=_("The teacher who carries out the activity."),
    )
    coordination = models.ForeignKey(
        Coordination,
        on_delete=models.PROTECT,  # a coordination that wrote data cannot be removed
        related_name="other_activities",
        verbose_name=_("coordenação"),
        help_text=_("Coordination of the teacher when the activity was entered; it owns the cell."),
    )
    kind = models.CharField(
        _("tipo"),
        max_length=30,
        choices=Kind.choices,
        help_text=_("Teaching complements, research, or management and services."),
    )
    description = models.CharField(
        _("descrição"),
        max_length=300,
        help_text=_("What the activity is (for example the research project or the body)."),
    )
    weekly_hours = models.DecimalField(
        _("horas semanais"),
        max_digits=5,
        decimal_places=2,
        help_text=_("Weekly hours of the activity in the semester, like the teaching hours."),
    )

    class Meta:
        verbose_name = _("outra atividade")
        verbose_name_plural = _("outras atividades")
        ordering = ["dsd_semester", "teacher", "kind", "pk"]
        constraints = [
            # An activity with no hours would count for nothing.
            models.CheckConstraint(
                condition=models.Q(weekly_hours__gt=0), name="other_activity_hours_positive"
            ),
        ]
        indexes = [
            # The load of a semester reads every activity of the semester at once.
            models.Index(fields=["dsd_semester", "teacher"], name="other_activity_sem_teacher"),
        ]

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell: the semester and the coordination stored with the activity."""
        return (self.dsd_semester_id, self.coordination_id)

    def __str__(self) -> str:
        return f"{self.teacher} – {self.get_kind_display()}: {self.description}"


class AcceptedExtraHours(GuardedDsdWrites, VersionedModel):
    """The extra hours a teacher accepted in a DSD, recorded by the coordinator (T5.4, D13, D96).

    One record per teacher and DSD (the year), with the hours accepted. Whether they cover the
    excess over the maximum is computed, not stored. The record belongs to the year, not to a
    semester, but the write guard needs a cell: ``dsd_semester`` is the semester through which it
    was last written (any of the two that was writable) and ``coordination`` is the teacher's
    coordination at that moment.
    """

    dsd = models.ForeignKey(
        Dsd,
        on_delete=models.PROTECT,  # a DSD with records cannot be removed
        related_name="accepted_extra_hours",
        verbose_name=_("DSD"),
        help_text=_("The DSD (academic year) the acceptance is valid for."),
    )
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.PROTECT,  # a teacher with records cannot be deleted (T0.5)
        related_name="accepted_extra_hours",
        verbose_name=_("docente"),
        help_text=_("The teacher who accepted the extra hours."),
    )
    dsd_semester = models.ForeignKey(
        DsdSemester,
        on_delete=models.PROTECT,  # the semester through which the record was written
        related_name="accepted_extra_hours",
        verbose_name=_("semestre do DSD"),
        help_text=_("Semester whose cell was used for the last write; it is not a validity."),
    )
    coordination = models.ForeignKey(
        Coordination,
        on_delete=models.PROTECT,  # a coordination that wrote data cannot be removed
        related_name="accepted_extra_hours",
        verbose_name=_("coordenação"),
        help_text=_("Coordination of the teacher at the last write; it owns the cell."),
    )
    hours = models.DecimalField(
        _("horas aceites"),
        max_digits=5,
        decimal_places=2,
        help_text=_("Weekly hours over the maximum that the teacher accepted."),
    )

    class Meta:
        verbose_name = _("horas extra aceites")
        verbose_name_plural = _("horas extra aceites")
        ordering = ["dsd", "teacher"]
        constraints = [
            # One acceptance per teacher and year; it is changed, not duplicated (Q13).
            models.UniqueConstraint(fields=["dsd", "teacher"], name="one_accepted_extra_per_year"),
            # Accepting nothing is clearing the record.
            models.CheckConstraint(
                condition=models.Q(hours__gt=0), name="accepted_extra_hours_positive"
            ),
        ]

    # The cell a delete goes through, set by the service for that call only: the stored
    # semester and coordination must stay as they were so that the audit keeps them.
    _write_cell: tuple[int, int] | None = None

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell used to write the record: the one set for the call, or its own."""
        return self._write_cell or (self.dsd_semester_id, self.coordination_id)

    def __str__(self) -> str:
        return f"{self.teacher} – {self.hours} h ({self.dsd})"


class BelowMinimumReason(GuardedDsdWrites, VersionedModel):
    """The reason a coordinator gives for a teacher whose load is below the minimum (T5.5, D16).

    One record per teacher and DSD (the year), like ``AcceptedExtraHours``: it is written through
    the cell of any writable semester of the year, which is stored here for the write guard.
    Changing the text bumps ``version``; the Executive Board's review belongs to one version, so a
    changed text goes back to pending (D97).
    """

    dsd = models.ForeignKey(
        Dsd,
        on_delete=models.PROTECT,  # a DSD with records cannot be removed
        related_name="minimum_reasons",
        verbose_name=_("DSD"),
        help_text=_("The DSD (academic year) the reason is valid for."),
    )
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.PROTECT,  # a teacher with records cannot be deleted (T0.5)
        related_name="minimum_reasons",
        verbose_name=_("docente"),
        help_text=_("The teacher whose load is below the minimum."),
    )
    dsd_semester = models.ForeignKey(
        DsdSemester,
        on_delete=models.PROTECT,  # the semester through which the record was written
        related_name="minimum_reasons",
        verbose_name=_("semestre do DSD"),
        help_text=_("Semester whose cell was used for the last write; it is not a validity."),
    )
    coordination = models.ForeignKey(
        Coordination,
        on_delete=models.PROTECT,  # a coordination that wrote data cannot be removed
        related_name="minimum_reasons",
        verbose_name=_("coordenação"),
        help_text=_("Coordination of the teacher at the last write; it owns the cell."),
    )
    text = models.TextField(
        _("motivo"), help_text=_("Why the teacher's load is below the minimum of their range.")
    )

    class Meta:
        verbose_name = _("motivo abaixo da mínima")
        verbose_name_plural = _("motivos abaixo da mínima")
        ordering = ["dsd", "teacher"]
        constraints = [
            # One reason per teacher and year; it is changed, not duplicated.
            models.UniqueConstraint(fields=["dsd", "teacher"], name="one_minimum_reason_per_year"),
        ]

    # The cell a write goes through, set by the service for that call only (see D96).
    _write_cell: tuple[int, int] | None = None

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell used to write the record: the one set for the call, or its own."""
        return self._write_cell or (self.dsd_semester_id, self.coordination_id)

    def __str__(self) -> str:
        return f"{self.teacher} – {self.dsd}"


class BelowMinimumReview(models.Model):
    """The Executive Board's decision on a reason for a load below the minimum (T5.5, D16, D97).

    One decision per reason, replaced when the board decides again (every decision is audited).
    ``reviewed_version`` is the version of the text that was reviewed: a decision about an older
    text does not count. It is not DSD cell data, so it is not written through ``dsd_write``.
    """

    class Decision(models.TextChoices):
        """What the board decided."""

        ACCEPTED = "accepted", _("Aceite")
        REFUSED = "refused", _("Recusado")

    reason = models.OneToOneField(
        BelowMinimumReason,
        on_delete=models.PROTECT,  # a reviewed reason is not erased
        related_name="review",
        verbose_name=_("motivo"),
        help_text=_("The reason the decision is about."),
    )
    reviewed_version = models.PositiveIntegerField(
        _("versão avaliada"), help_text=_("Version of the reason text that was reviewed.")
    )
    decision = models.CharField(
        _("decisão"), max_length=10, choices=Decision.choices, help_text=_("Accepted or refused.")
    )
    comment = models.TextField(
        _("comentário"),
        blank=True,
        help_text=_("Why it was refused (required then); optional when accepted."),
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # the author of a decision is never lost
        related_name="minimum_reviews",
        verbose_name=_("avaliado por"),
        help_text=_("The Executive Board user who decided."),
    )
    reviewed_at = models.DateTimeField(
        _("avaliado em"), auto_now=True, help_text=_("When the decision was last taken.")
    )

    class Meta:
        verbose_name = _("avaliação do motivo")
        verbose_name_plural = _("avaliações dos motivos")

    def __str__(self) -> str:
        return f"{self.reason} – {self.get_decision_display()}"


_TENDER_STATE_LABELS = {
    TenderState.PROPOSED: _("Proposta, à espera do Conselho"),
    TenderState.REFUSED: _("Recusada pelo Conselho"),
    TenderState.APPROVED: _("Aprovada pelo Conselho"),
    TenderState.INVITED: _("Docente convidado"),
    TenderState.ACCEPTED: _("Convite aceite"),
    TenderState.TENDER: _("A concurso"),
    TenderState.FILLED: _("Docente atribuído"),
    TenderState.WITHDRAWN: _("Retirada"),
}
TENDER_STATE_CHOICES = [(state.value, _TENDER_STATE_LABELS[state]) for state in TenderState]


class TenderProposal(VersionedModel):
    """A proposal to put a teaching unit to tender, from the coordinator to the board (block 5).

    The coordinator proposes a unit that no teacher of the coordination can take, with a
    justification. The Executive Board refuses it (back to the coordinator) or approves it and
    then invites a collaborator or launches the tender; the unit is filled by the coordinator
    (an accepted collaborator) or by the PGC manager (the teacher the tender obtained). The state
    machine lives in ``tender_rules``; every step is kept in ``TenderEvent``. The state is changed
    by actors with different cell rules (the board decides without a cell, D97), so the model is
    exempt from the write guard and the services check the cell where it matters. See D17, D46,
    D105.
    """

    class ReasonKind(models.TextChoices):
        """The usual reasons a coordinator gives (05): the three of the specification and others."""

        NO_PROFILE = "no_profile", _("Não há docente da coordenação com o perfil")
        NOT_ENOUGH_HOURS = (
            "not_enough_hours",
            _("Os docentes que há não chegam para a carga horária"),
        )
        NO_EXTRA_HOURS = "no_extra_hours", _("Os docentes que há não aceitam horas extra")
        OTHER = "other", _("Outro motivo (descrito na justificação)")

    unit = models.ForeignKey(
        TeachingUnit,
        on_delete=models.CASCADE,  # a unit that disappears takes its closed proposals with it
        related_name="tender_proposals",
        verbose_name=_("unidade letiva"),
        help_text=_("The teaching unit that has no teacher."),
    )
    state = models.CharField(
        _("estado"),
        max_length=20,
        choices=TENDER_STATE_CHOICES,
        default=TenderState.PROPOSED.value,
        help_text=_("Where the proposal stands (see tender_rules)."),
    )
    reason_kind = models.CharField(
        _("tipo de motivo"),
        max_length=20,
        choices=ReasonKind.choices,
        help_text=_("The usual reason for the proposal."),
    )
    justification = models.TextField(
        _("justificação"), help_text=_("Why no teacher of the coordination can take the unit.")
    )
    suggested_teacher = models.ForeignKey(
        Teacher,
        null=True,
        blank=True,
        on_delete=models.PROTECT,  # a teacher in a proposal cannot be deleted
        related_name="suggested_for_tenders",
        verbose_name=_("colaborador sugerido"),
        help_text=_("The collaborator the coordinator suggests, if any (D46)."),
    )
    invited_teacher = models.ForeignKey(
        Teacher,
        null=True,
        blank=True,
        on_delete=models.PROTECT,  # a teacher in a proposal cannot be deleted
        related_name="invited_for_tenders",
        verbose_name=_("colaborador convidado"),
        help_text=_("The collaborator the board invited, if any."),
    )
    board_comment = models.TextField(
        _("comentário do Conselho"),
        blank=True,
        help_text=_("Why the board refused the proposal (required then)."),
    )

    class Meta:
        verbose_name = _("proposta de concurso")
        verbose_name_plural = _("propostas de concurso")
        ordering = ["-pk"]
        constraints = [
            # A unit has at most one proposal that is still open (not filled and not withdrawn):
            # two coordinators cannot open it at the same time.
            models.UniqueConstraint(
                fields=["unit"],
                condition=~models.Q(
                    state__in=[TenderState.FILLED.value, TenderState.WITHDRAWN.value]
                ),
                name="one_open_tender_per_unit",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.unit} – {self.get_state_display()}"


class TenderEvent(models.Model):
    """One step in the life of a tender proposal: who did what, when, with which comment.

    It is the history the specification asks for (state and history of each proposal) and it
    survives only as long as the proposal does; the audit trail keeps the changes of every row.
    """

    proposal = models.ForeignKey(
        TenderProposal,
        on_delete=models.CASCADE,  # the history belongs to its proposal
        related_name="events",
        verbose_name=_("proposta"),
        help_text=_("The proposal the step belongs to."),
    )
    from_state = models.CharField(
        _("estado anterior"),
        max_length=20,
        blank=True,
        help_text=_("The state before the step; empty for the proposal itself."),
    )
    to_state = models.CharField(
        _("estado novo"), max_length=20, help_text=_("The state after the step.")
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,  # the author of a step is never lost
        related_name="tender_events",
        verbose_name=_("autor"),
        help_text=_("Who did it."),
    )
    comment = models.TextField(_("comentário"), blank=True, help_text=_("What they said."))
    created_at = models.DateTimeField(
        _("data"), auto_now_add=True, help_text=_("When the step happened.")
    )

    class Meta:
        verbose_name = _("passo da proposta")
        verbose_name_plural = _("passos da proposta")
        ordering = ["pk"]

    def __str__(self) -> str:
        return f"{self.proposal_id}: {self.from_state or '-'} → {self.to_state}"
