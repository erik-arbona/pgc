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

from .load_ranges import RangeRule, RuleKind


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


class LoadRange(models.Model):
    """A range of annual lesson hours with the date from which it applies (D58).

    One row is one rule for one subject: a category, a position or a teacher type
    (collaborator or competition teacher). The hours are weekly hours summed over both
    semesters (D12). The rule ends when a newer rule of the same subject starts, so rules of a
    subject cannot overlap. Values are entered by the PGC manager, never loaded by code.
    """

    class Kind(models.TextChoices):
        """What the rule refers to; same values as ``load_ranges.RuleKind``."""

        CATEGORY = "category", _("Categoria")
        POSITION = "position", _("Cargo")
        TEACHER_TYPE = "teacher_type", _("Tipo de docente")

    kind = models.CharField(
        _("tipo de regra"),
        max_length=20,
        choices=Kind.choices,
        help_text=_("Whether the rule is for a category, a position or a teacher type."),
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,  # a category with rules cannot be removed
        null=True,
        blank=True,
        related_name="load_ranges",
        verbose_name=_("categoria"),
        help_text=_("Set only for category rules."),
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,  # a position with rules cannot be removed
        null=True,
        blank=True,
        related_name="load_ranges",
        verbose_name=_("cargo"),
        help_text=_("Set only for position rules."),
    )
    teacher_type = models.CharField(
        _("tipo de docente"),
        max_length=30,
        null=True,
        blank=True,
        choices=[
            (Teacher.Type.HABITUAL_COLLABORATOR, Teacher.Type.HABITUAL_COLLABORATOR.label),
            (Teacher.Type.COMPETITION, Teacher.Type.COMPETITION.label),
        ],
        help_text=_("Set only for teacher-type rules; full-time teachers use category ranges."),
    )
    minimum_hours = models.DecimalField(
        _("mínimo"),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Minimum weekly hours summed over both semesters; optional for teacher types."),
    )
    maximum_hours = models.DecimalField(
        _("máximo"),
        max_digits=5,
        decimal_places=2,
        help_text=_("Maximum weekly hours summed over both semesters."),
    )
    valid_from = models.DateField(
        _("vigora desde"),
        help_text=_("First day on which the rule applies; it ends when a newer rule starts."),
    )

    class Meta:
        verbose_name = _("intervalo de horas letivas")
        verbose_name_plural = _("intervalos de horas letivas")
        ordering = ["kind", "category_id", "position_id", "teacher_type", "-valid_from"]
        constraints = [
            # Exactly the reference that matches the kind is set, and no other.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="category",
                        category__isnull=False,
                        position__isnull=True,
                        teacher_type__isnull=True,
                    )
                    | models.Q(
                        kind="position",
                        position__isnull=False,
                        category__isnull=True,
                        teacher_type__isnull=True,
                    )
                    | models.Q(
                        kind="teacher_type",
                        teacher_type__isnull=False,
                        category__isnull=True,
                        position__isnull=True,
                    )
                ),
                name="load_range_one_matching_reference",
            ),
            # Only collaborators and competition teachers have type ranges (D58).
            models.CheckConstraint(
                condition=models.Q(teacher_type__isnull=True)
                | models.Q(teacher_type__in=["habitual_collaborator", "competition"]),
                name="load_range_type_not_full_time",
            ),
            models.CheckConstraint(
                condition=models.Q(maximum_hours__gte=0), name="load_range_maximum_not_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_hours__isnull=True)
                | (
                    models.Q(minimum_hours__gte=0)
                    & models.Q(minimum_hours__lte=models.F("maximum_hours"))
                ),
                name="load_range_minimum_within_maximum",
            ),
            # D11 asks for a minimum; D46 makes it optional only for the teacher types.
            models.CheckConstraint(
                condition=models.Q(kind="teacher_type") | models.Q(minimum_hours__isnull=False),
                name="load_range_minimum_required_except_types",
            ),
            # One rule per subject and start date, so the rules of a subject never overlap.
            models.UniqueConstraint(
                fields=["category", "valid_from"],
                condition=models.Q(kind="category"),
                name="unique_load_range_category_start",
            ),
            models.UniqueConstraint(
                fields=["position", "valid_from"],
                condition=models.Q(kind="position"),
                name="unique_load_range_position_start",
            ),
            models.UniqueConstraint(
                fields=["teacher_type", "valid_from"],
                condition=models.Q(kind="teacher_type"),
                name="unique_load_range_type_start",
            ),
        ]

    def __str__(self) -> str:
        subject = self.category or self.position or self.get_teacher_type_display()
        return f"{subject}: {self.maximum_hours} h desde {self.valid_from}"

    def to_rule(self) -> RangeRule:
        """Return the plain rule the domain function ``resolve_load_range`` works with."""
        if self.kind == self.Kind.CATEGORY:
            ref: int | str = self.category_id
        elif self.kind == self.Kind.POSITION:
            ref = self.position_id
        else:
            ref = self.teacher_type
        return RangeRule(
            id=self.pk,
            kind=RuleKind(self.kind),
            ref=ref,
            minimum=self.minimum_hours,
            maximum=self.maximum_hours,
            valid_from=self.valid_from,
        )
