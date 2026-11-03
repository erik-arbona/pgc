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

    class Meta:
        verbose_name = _("unidade letiva")
        verbose_name_plural = _("unidades letivas")
        ordering = ["offering", "class_type__position", "pk"]

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell of the offering the unit belongs to."""
        return self.offering.dsd_cell()

    def __str__(self) -> str:
        return f"{self.offering} – {self.class_type.code}"


class TeachingUnitMember(GuardedDsdWrites, models.Model):
    """A turma that attends a teaching unit as a whole turma (T3.1).

    It points at the offering link (not at the turma), so that a merge across courses (T3.4) can
    hold links of another offering. ``class_type`` repeats the unit's, only to let the database
    guarantee that a turma attends each class type once as a whole turma.
    """

    unit = models.ForeignKey(
        TeachingUnit,
        on_delete=models.CASCADE,  # the members only exist inside their unit
        related_name="members",
        verbose_name=_("unidade letiva"),
        help_text=_("Unit the turma attends."),
    )
    class_group_link = models.ForeignKey(
        OfferingClassGroup,
        on_delete=models.PROTECT,  # a link with units cannot be deleted
        related_name="unit_memberships",
        verbose_name=_("turma da oferta"),
        help_text=_("The turma of the offering that attends the unit."),
    )
    class_type = models.ForeignKey(
        ClassType,
        on_delete=models.PROTECT,  # a class type in use cannot be removed
        related_name="unit_memberships",
        verbose_name=_("tipo de aula"),
        help_text=_("Copy of the unit's class type; it must be the same."),
    )

    class Meta:
        verbose_name = _("turma da unidade letiva")
        verbose_name_plural = _("turmas da unidade letiva")
        ordering = ["unit", "class_group_link"]
        constraints = [
            # A turma attends each class type once as a whole turma: the idempotency key of the
            # generation and the rule that merges (T3.3) will rely on.
            models.UniqueConstraint(
                fields=["class_group_link", "class_type"],
                name="one_whole_unit_per_turma_and_type",
            ),
        ]

    def dsd_cell(self) -> tuple[int, int]:
        """Return the cell of the unit the member belongs to."""
        return self.unit.dsd_cell()

    def clean(self) -> None:
        """Check that the copy of the class type is the unit's.

        Raises:
            ValidationError: if the class type differs from the unit's.
        """
        if self.class_type_id != self.unit.class_type_id:
            raise ValidationError(
                {"class_type": _("O tipo de aula tem de ser o da unidade letiva.")}
            )

    def save(self, *args, **kwargs) -> None:
        """Validate the class type before saving."""
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.unit} – {self.class_group_link.class_group}"
