"""Models of ``academic``: faculty, coordination, course and academic year.

Implements: docs/especificacao/04_modelo_de_dados.md – Faculty, Coordination, Course;
docs/glossario.md – AcademicYear. Study plans and subjects arrive with T2.2.
All writes should go through ``apps.core.audit.audited_save`` (CLAUDE.md rule 7).
See D42 for the assumptions behind these models.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Faculty(models.Model):
    """A Faculty: the organic unit that groups courses and coordinations.

    Permission scopes of kind ``faculty`` refer to its primary key (see ``core.RoleAssignment``).
    """

    name = models.CharField(_("nome"), max_length=200, help_text=_("Full name of the Faculty."))
    code = models.CharField(
        _("código"),
        max_length=20,
        unique=True,  # one code per Faculty, used to refer to it in imports and reports
        help_text=_("Short unique code, e.g. 'FCT'."),
    )

    class Meta:
        verbose_name = _("faculdade")
        verbose_name_plural = _("faculdades")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Coordination(models.Model):
    """A coordination (disciplinary group).

    It manages the subjects of its area in every course where they appear and has teachers.
    Assumption D42: it belongs to a single Faculty.
    """

    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.PROTECT,  # never remove a Faculty that still has coordinations
        related_name="coordinations",
        verbose_name=_("faculdade"),
        help_text=_("Faculty the coordination belongs to."),
    )
    name = models.CharField(_("nome"), max_length=200, help_text=_("Name of the coordination."))

    class Meta:
        verbose_name = _("coordenação")
        verbose_name_plural = _("coordenações")
        ordering = ["faculty__name", "name"]
        constraints = [
            # The same name may exist in two Faculties, but not twice in one.
            models.UniqueConstraint(fields=["faculty", "name"], name="unique_coordination_name"),
        ]

    def __str__(self) -> str:
        return self.name


class Course(models.Model):
    """A course, from bachelor ('licenciatura') to doctorate, with its study plan (T2.2)."""

    class Level(models.TextChoices):
        """Academic level of the course."""

        BACHELOR = "bachelor", _("Licenciatura")
        MASTER = "master", _("Mestrado")
        DOCTORATE = "doctorate", _("Doutoramento")

    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.PROTECT,  # never remove a Faculty that still has courses
        related_name="courses",
        verbose_name=_("faculdade"),
        help_text=_("Faculty that runs the course."),
    )
    name = models.CharField(_("nome"), max_length=200, help_text=_("Name of the course."))
    level = models.CharField(
        _("grau"),
        max_length=16,
        choices=Level.choices,
        help_text=_("Bachelor, master or doctorate."),
    )

    class Meta:
        verbose_name = _("curso")
        verbose_name_plural = _("cursos")
        ordering = ["faculty__name", "name", "level"]
        constraints = [
            # A bachelor and a master may share a name; faculty + name + level identify a course.
            models.UniqueConstraint(
                fields=["faculty", "name", "level"], name="unique_course_in_faculty"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_level_display()})"


class AcademicYear(models.Model):
    """An academic year: the yearly period of the DSD and of the exams.

    Only the start year is stored (D42); dates and semesters are not in the specification.
    """

    start_year = models.PositiveSmallIntegerField(
        _("ano de início"),
        unique=True,  # a single academic year per start year
        help_text=_("Calendar year in which the academic year starts, e.g. 2026."),
    )

    class Meta:
        verbose_name = _("ano letivo")
        verbose_name_plural = _("anos letivos")
        ordering = ["-start_year"]

    @property
    def label(self) -> str:
        """Return the display label, e.g. ``2026/2027``."""
        return f"{self.start_year}/{self.start_year + 1}"

    def __str__(self) -> str:
        return self.label
