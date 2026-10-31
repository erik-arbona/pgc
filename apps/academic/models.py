"""Models of ``academic``: academic structure, study plans and subjects.

Implements: docs/especificacao/04_modelo_de_dados.md – Faculty, Coordination, Course,
study plan, subject; docs/glossario.md – AcademicYear, ClassType.
All writes should go through ``apps.core.audit.audited_save`` (CLAUDE.md rule 7).
See D42 and D44 for the assumptions behind these models.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
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


class StudyPlan(models.Model):
    """The study plan of a course, versioned by the academic year in which it starts.

    A plan applies until the next plan of the same course starts (D44).
    """

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,  # never remove a course that still has plans
        related_name="study_plans",
        verbose_name=_("curso"),
        help_text=_("Course the plan belongs to."),
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,  # the year is part of the plan's identity
        related_name="study_plans",
        verbose_name=_("ano letivo de início"),
        help_text=_("Academic year in which this version of the plan starts."),
    )

    class Meta:
        verbose_name = _("plano de estudos")
        verbose_name_plural = _("planos de estudos")
        ordering = ["course", "-academic_year__start_year"]
        constraints = [
            # One version of a course's plan per starting year.
            models.UniqueConstraint(
                fields=["course", "academic_year"], name="unique_study_plan_per_year"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.course} – {self.academic_year}"


class ClassType(models.Model):
    """A type of class (T, TP, P, L, other), configured by the PGC manager (D45).

    The initial types are loaded by a data migration; further ones are added as data, never
    in code. A type in use is deactivated instead of deleted.
    """

    code = models.CharField(
        _("código"),
        max_length=10,
        unique=True,  # subjects refer to the type by this code
        help_text=_("Short unique code, e.g. 'TP'."),
    )
    name = models.CharField(_("nome"), max_length=100, help_text=_("Name of the class type."))
    is_active = models.BooleanField(
        _("ativo"),
        default=True,
        help_text=_("Inactive types cannot be given to subjects; existing loads keep them."),
    )
    position = models.PositiveSmallIntegerField(
        _("posição"), default=100, help_text=_("Display order; lower values come first.")
    )

    class Meta:
        verbose_name = _("tipo de aula")
        verbose_name_plural = _("tipos de aula")
        ordering = ["position", "code"]

    def __str__(self) -> str:
        return self.code


class Subject(models.Model):
    """A subject (UC) of a study plan.

    The semester load is one total per subject; the weekly load is split by class type
    in ``SubjectClassLoad`` (D44). The programme text arrives with T2.4.
    """

    study_plan = models.ForeignKey(
        StudyPlan,
        on_delete=models.PROTECT,  # never remove a plan that still has subjects
        related_name="subjects",
        verbose_name=_("plano de estudos"),
        help_text=_("Study plan the subject belongs to."),
    )
    code = models.CharField(
        _("código"), max_length=20, help_text=_("Subject code, unique within the plan.")
    )
    name = models.CharField(_("nome"), max_length=200, help_text=_("Name of the subject."))
    ects = models.DecimalField(
        _("ECTS"), max_digits=4, decimal_places=2, help_text=_("ECTS credits.")
    )
    curricular_year = models.PositiveSmallIntegerField(
        _("ano curricular"), help_text=_("Year of the course in which the subject is taught.")
    )
    semester = models.PositiveSmallIntegerField(
        _("semestre"), help_text=_("Semester of the curricular year: 1 or 2.")
    )
    coordination = models.ForeignKey(
        Coordination,
        on_delete=models.PROTECT,  # never remove a coordination that owns subjects
        related_name="subjects",
        verbose_name=_("coordenação responsável"),
        help_text=_("Coordination responsible for the subject."),
    )
    semester_hours = models.DecimalField(
        _("carga semestral"),
        max_digits=6,
        decimal_places=2,
        help_text=_("Total contact hours in the semester."),
    )

    class Meta:
        verbose_name = _("disciplina")
        verbose_name_plural = _("disciplinas")
        ordering = ["study_plan", "curricular_year", "semester", "code"]
        constraints = [
            # The code identifies the subject inside one plan version (D44).
            models.UniqueConstraint(fields=["study_plan", "code"], name="unique_subject_code"),
            models.CheckConstraint(condition=models.Q(ects__gt=0), name="subject_ects_positive"),
            models.CheckConstraint(
                condition=models.Q(curricular_year__gte=1), name="subject_year_at_least_one"
            ),
            models.CheckConstraint(
                condition=models.Q(semester__in=[1, 2]), name="subject_semester_one_or_two"
            ),
            models.CheckConstraint(
                condition=models.Q(semester_hours__gte=0),
                name="subject_semester_hours_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"

    @property
    def weekly_hours_total(self) -> Decimal:
        """Return the weekly hours summed over all class types (0 when there are none)."""
        total = self.class_loads.aggregate(total=Sum("weekly_hours"))["total"]
        return total if total is not None else Decimal("0")


class SubjectClassLoad(models.Model):
    """Weekly hours of one class type of a subject (e.g. 2 h of T per week)."""

    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,  # delete loads explicitly so the audit log records them
        related_name="class_loads",
        verbose_name=_("disciplina"),
        help_text=_("Subject the weekly hours belong to."),
    )
    class_type = models.ForeignKey(
        ClassType,
        on_delete=models.PROTECT,  # a class type in use cannot be removed
        related_name="subject_loads",
        verbose_name=_("tipo de aula"),
        help_text=_("Type of class."),
    )
    weekly_hours = models.DecimalField(
        _("horas semanais"),
        max_digits=4,
        decimal_places=2,
        help_text=_("Weekly hours of this class type."),
    )

    class Meta:
        verbose_name = _("carga semanal por tipo de aula")
        verbose_name_plural = _("cargas semanais por tipo de aula")
        ordering = ["subject", "class_type"]
        constraints = [
            # A subject lists each class type once; hours add up in the weekly total.
            models.UniqueConstraint(
                fields=["subject", "class_type"], name="unique_class_load_per_type"
            ),
            models.CheckConstraint(
                condition=models.Q(weekly_hours__gt=0), name="class_load_hours_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.subject.code} {self.class_type.code} {self.weekly_hours} h"

    def save(self, *args, **kwargs) -> None:
        """Save the load, refusing an inactive class type on a new row.

        Raises:
            ValidationError: if the load is new and its class type is inactive (D45).
        """
        if self._state.adding and not self.class_type.is_active:
            raise ValidationError({"class_type": _("Este tipo de aula está desativado.")})
        super().save(*args, **kwargs)
