"""Models of the DSD: the DSD, its semesters, their states, the offerings and the units.

Implements: docs/especificacao/04_modelo_de_dados.md – DSD; docs/backlog_fase2.md T2.1.
See D43: a single DSD per academic year for the whole University, created only by the PGC
manager. The state of each semester per coordination (open, closed) comes with T2.2.
"""

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
