"""Models of the DSD: the DSD of an academic year and its two semesters (T2.1).

Implements: docs/especificacao/04_modelo_de_dados.md – DSD; docs/backlog_fase2.md T2.1.
See D43: a single DSD per academic year for the whole University, created only by the PGC
manager. The state of each semester per coordination (open, closed) comes with T2.2.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.academic.models import AcademicYear, Coordination
from apps.core.models import VersionedModel


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
