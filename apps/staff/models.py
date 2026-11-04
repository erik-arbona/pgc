"""Models of ``staff``: teachers, categories, positions and position assignments.

Implements: docs/especificacao/04_modelo_de_dados.md – teacher; 02_perfis_e_dados.md – teachers,
categories and positions entered by the PGC manager. Hour ranges (T3.2) will refer to
``Category``, ``Position`` and ``Teacher.Type``. See D46 and D56.
All writes should go through ``apps.core.audit.audited_save`` (CLAUDE.md rule 7).
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.academic.models import Coordination
from apps.core.models import Profile, RoleAssignment, ScopeKind


class Category(models.Model):
    """Scientific degree of a teacher (licenciado, mestre, doutor), configurable data.

    The initial three are loaded by a data migration; the PGC manager can add more (D56).
    """

    code = models.CharField(
        _("código"), max_length=10, unique=True, help_text=_("Short unique code, e.g. 'DOU'.")
    )
    name = models.CharField(
        _("nome"), max_length=100, unique=True, help_text=_("Name of the category.")
    )
    is_active = models.BooleanField(
        _("ativa"),
        default=True,
        help_text=_("Inactive categories are not offered for new teachers."),
    )
    position = models.PositiveSmallIntegerField(
        _("posição"), default=100, help_text=_("Display order; lower values come first.")
    )

    class Meta:
        verbose_name = _("categoria")
        verbose_name_plural = _("categorias")
        ordering = ["position", "code"]

    def __str__(self) -> str:
        return self.name


class Position(models.Model):
    """A position (cargo), such as adviser or council president, held by a full-time teacher.

    A position can change the teacher's hours range (T3.2). Configurable data with no initial
    values: the specification only gives examples (D46, D56).
    """

    name = models.CharField(
        _("nome"), max_length=100, unique=True, help_text=_("Name of the position.")
    )
    is_active = models.BooleanField(
        _("ativo"),
        default=True,
        help_text=_("Inactive positions are not assigned to anyone new."),
    )
    position = models.PositiveSmallIntegerField(
        _("posição"), default=100, help_text=_("Display order; lower values come first.")
    )

    class Meta:
        verbose_name = _("cargo")
        verbose_name_plural = _("cargos")
        ordering = ["position", "name"]

    def __str__(self) -> str:
        return self.name


class Teacher(models.Model):
    """A teacher: one person across all courses (07_arquitetura – integrity).

    The account of a teacher is linked through a ``RoleAssignment`` of profile ``teacher``
    whose scope id is this teacher's id (D38); there is no foreign key to the user (D56).
    """

    class Type(models.TextChoices):
        """Kinds of teacher; each has its own hours range (D46)."""

        FULL_TIME = "full_time", _("Tempo inteiro")
        HABITUAL_COLLABORATOR = "habitual_collaborator", _("Colaborador habitual")
        COMPETITION = "competition", _("Docente de concurso")

    identifier = models.CharField(
        _("identificador"),
        max_length=30,
        help_text=_("Unique identifier of the teacher in the University (case-insensitive)."),
    )
    name = models.CharField(_("nome"), max_length=200, help_text=_("Full name."))
    coordination = models.ForeignKey(
        Coordination,
        on_delete=models.PROTECT,  # never remove a coordination that still has teachers
        related_name="teachers",
        verbose_name=_("coordenação"),
        help_text=_("Coordination the teacher belongs to; it defines their Faculty."),
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,  # a category in use cannot be removed
        related_name="teachers",
        verbose_name=_("categoria"),
        help_text=_("Scientific degree."),
    )
    teacher_type = models.CharField(
        _("tipo de docente"),
        max_length=30,
        choices=Type.choices,
        help_text=_("Full-time, habitual collaborator or competition teacher (D46)."),
    )
    is_active = models.BooleanField(
        _("ativo"),
        default=True,
        help_text=_("Inactive teachers are not offered for new assignments."),
    )

    class Meta:
        verbose_name = _("docente")
        verbose_name_plural = _("docentes")
        ordering = ["name", "identifier"]
        constraints = [
            # One teacher per identifier, whatever the letter case.
            models.UniqueConstraint(Lower("identifier"), name="unique_teacher_identifier_ci"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.identifier})"

    def save(self, *args, **kwargs) -> None:
        """Save the teacher, refusing a type change that would leave positions on a non-full-time.

        Raises:
            ValidationError: if the teacher holds positions and is no longer full-time (D56).
        """
        if (
            self.pk
            and self.teacher_type != self.Type.FULL_TIME
            and self.position_assignments.exists()
        ):
            raise ValidationError(
                {"teacher_type": _("Remova primeiro os cargos: só o tempo inteiro os tem.")}
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Delete the teacher unless an account role still points at them (D38).

        Raises:
            ProtectedError: if a role assignment of kind teacher refers to this teacher.
        """
        roles = RoleAssignment.objects.filter(
            profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER, scope_id=self.pk
        )
        if roles.exists():
            raise models.ProtectedError(
                "A teacher with an account role cannot be deleted.", set(roles)
            )
        return super().delete(*args, **kwargs)


class TeacherPosition(models.Model):
    """A position held by a full-time teacher. No dates for now; the audit log keeps history."""

    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.CASCADE,  # the service audits each row before deleting the teacher
        related_name="position_assignments",
        verbose_name=_("docente"),
        help_text=_("Teacher holding the position."),
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,  # a position in use cannot be removed
        related_name="assignments",
        verbose_name=_("cargo"),
        help_text=_("Position held."),
    )

    class Meta:
        verbose_name = _("cargo atribuído")
        verbose_name_plural = _("cargos atribuídos")
        ordering = ["teacher", "position"]
        constraints = [
            models.UniqueConstraint(fields=["teacher", "position"], name="unique_teacher_position"),
        ]

    def __str__(self) -> str:
        return f"{self.teacher} – {self.position}"

    def save(self, *args, **kwargs) -> None:
        """Save the assignment after checking the teacher type and the position status.

        Raises:
            ValidationError: if the teacher is not full-time, or if a new assignment uses an
                inactive position (D56).
        """
        if self.teacher.teacher_type != Teacher.Type.FULL_TIME:
            raise ValidationError(_("Só os docentes a tempo inteiro têm cargos."))
        if self._state.adding and not self.position.is_active:
            raise ValidationError({"position": _("Este cargo está desativado.")})
        super().save(*args, **kwargs)
