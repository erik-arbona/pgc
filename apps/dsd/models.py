"""Models of the DSD: the DSD of an academic year and its two semesters (T2.1).

Implements: docs/especificacao/04_modelo_de_dados.md – DSD; docs/backlog_fase2.md T2.1.
See D43: a single DSD per academic year for the whole University, created only by the PGC
manager. The state of each semester per coordination (open, closed) comes with T2.2.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.academic.models import AcademicYear


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
