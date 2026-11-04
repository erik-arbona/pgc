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

from .class_groups import curricular_year_in


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
    preparation_weight = models.DecimalField(
        _("peso na preparação"),
        max_digits=4,
        decimal_places=2,
        default=0,
        help_text=_(
            "How many preparation hours each weekly hour of this type adds (D61); "
            "0 means it does not count. A new type starts at 0."
        ),
    )

    class Meta:
        verbose_name = _("tipo de aula")
        verbose_name_plural = _("tipos de aula")
        ordering = ["position", "code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(preparation_weight__gte=0),
                name="class_type_preparation_weight_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return self.code


class Subject(models.Model):
    """A subject (UC) of a study plan.

    The semester load is one total per subject; the weekly load is split by class type
    in ``SubjectClassLoad`` (D44).
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

    programme = models.TextField(
        _("programa"),
        blank=True,
        help_text=_("Programme of the subject; cross-course subjects share the same one."),
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


class CrossCourseSubject(models.Model):
    """A group of equivalent subjects: the same programme taught in several courses (D22).

    Which subjects belong to it is in ``CrossCourseSubjectMember``; the courses in which
    classes may be merged are in ``CrossCourseSubjectCourse``. The relation rows are
    explicit models so that every change goes through ``audited_save``.
    """

    name = models.CharField(
        _("nome"), max_length=200, help_text=_("Name shown for the shared subject.")
    )
    notes = models.TextField(_("notas"), blank=True, help_text=_("Free notes of the manager."))

    class Meta:
        verbose_name = _("disciplina transversal")
        verbose_name_plural = _("disciplinas transversais")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CrossCourseSubjectMember(models.Model):
    """A subject of a study plan that belongs to a cross-course group."""

    cross_course_subject = models.ForeignKey(
        CrossCourseSubject,
        on_delete=models.CASCADE,  # members have no meaning without their group
        related_name="members",
        verbose_name=_("disciplina transversal"),
        help_text=_("Group the subject belongs to."),
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,  # a subject must leave the group before being deleted
        related_name="cross_course_memberships",
        verbose_name=_("disciplina"),
        help_text=_("Subject of a study plan."),
    )

    class Meta:
        verbose_name = _("membro de disciplina transversal")
        verbose_name_plural = _("membros de disciplina transversal")
        constraints = [
            # A subject belongs to at most one group (D47, to confirm).
            models.UniqueConstraint(fields=["subject"], name="unique_cross_course_membership"),
        ]

    def __str__(self) -> str:
        return f"{self.cross_course_subject} – {self.subject}"


class CrossCourseSubjectCourse(models.Model):
    """A course in which a cross-course subject may have merged classes (D22)."""

    cross_course_subject = models.ForeignKey(
        CrossCourseSubject,
        on_delete=models.CASCADE,  # meaningless without its group
        related_name="allowed_courses",
        verbose_name=_("disciplina transversal"),
        help_text=_("Group the permission belongs to."),
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,  # never remove a course that the rule refers to
        related_name="cross_course_subjects",
        verbose_name=_("curso"),
        help_text=_("Course whose classes may be merged."),
    )

    class Meta:
        verbose_name = _("curso de disciplina transversal")
        verbose_name_plural = _("cursos de disciplina transversal")
        constraints = [
            models.UniqueConstraint(
                fields=["cross_course_subject", "course"], name="unique_cross_course_course"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cross_course_subject} – {self.course}"


class ClassGroup(models.Model):
    """A turma: a cohort of students of a course that moves up one year every year (D49).

    It is created once, with its intake year, and keeps the study plan in force for the
    first year when it entered (D48). Its curricular year is computed, not stored. A course
    that does not open in some year simply has no turma for that intake year.
    """

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,  # never remove a course that still has turmas
        related_name="class_groups",
        verbose_name=_("curso"),
        help_text=_("Course of the turma."),
    )
    intake_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,  # the intake year is part of the turma's identity
        related_name="entering_class_groups",
        verbose_name=_("ano letivo de entrada"),
        help_text=_("Academic year in which the turma enters the first curricular year."),
    )
    label = models.CharField(
        _("etiqueta"),
        max_length=10,
        blank=True,
        help_text=_("Letter that tells turmas of the same year apart; empty if there is one."),
    )
    study_plan = models.ForeignKey(
        StudyPlan,
        on_delete=models.PROTECT,  # never remove a plan that a turma follows
        related_name="class_groups",
        verbose_name=_("plano de estudos"),
        help_text=_("Plan followed by the turma; fixed when it is created (D48)."),
    )
    last_academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ending_class_groups",
        verbose_name=_("último ano letivo"),
        help_text=_("Last academic year of the turma; empty while it is active."),
    )
    version = models.PositiveIntegerField(
        _("versão"),
        default=1,
        help_text=_("Optimistic lock: grows by one on every save (D54)."),
    )

    class Meta:
        verbose_name = _("turma")
        verbose_name_plural = _("turmas")
        ordering = ["course", "intake_year__start_year", "label"]
        constraints = [
            # One turma per course, intake year and label; an empty label is the default turma.
            models.UniqueConstraint(
                fields=["course", "intake_year", "label"], name="unique_class_group_label"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.course} {self.intake_year} {self.label}".strip()

    def curricular_year_in(self, academic_year: int) -> int | None:
        """Return the curricular year in an academic year, or ``None`` if not active then."""
        last = self.last_academic_year.start_year if self.last_academic_year else None
        return curricular_year_in(self.intake_year.start_year, academic_year, last)

    def save(self, *args, **kwargs) -> None:
        """Save after checking the turma's invariants.

        Raises:
            ValidationError: if the plan is not a plan of the course, if the plan is changed
                after creation, if the last academic year precedes the intake year, or if
                the version is stale because someone else saved first (D54).
        """
        if self.study_plan.course_id != self.course_id:
            raise ValidationError({"study_plan": _("O plano não pertence ao curso da turma.")})
        if (
            self.last_academic_year
            and self.last_academic_year.start_year < self.intake_year.start_year
        ):
            raise ValidationError(
                {"last_academic_year": _("O último ano letivo não pode ser anterior à entrada.")}
            )
        if not self._state.adding:
            stored = type(self).objects.filter(pk=self.pk).values_list("study_plan_id", flat=True)
            if stored and stored[0] != self.study_plan_id:
                raise ValidationError({"study_plan": _("Uma turma não muda de plano.")})
            # Optimistic lock: only the editor who saw the current version may save.
            updated = (
                type(self)
                .objects.filter(pk=self.pk, version=self.version)
                .update(version=models.F("version") + 1)
            )
            if not updated:
                raise ValidationError(
                    _("Esta turma foi alterada por outra pessoa. Recarregue a página.")
                )
            self.version += 1
        super().save(*args, **kwargs)
