"""Models of ``core``: user and role assignments (profile + scope).

Implements: docs/especificacao/07_arquitetura.md – Permissions (profile and scope per user).
Audit models arrive with T1.3.
"""

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.translation import gettext_lazy as _

from .roles import Profile, ScopeKind, scope_kind_allowed

__all__ = ["AuditEntry", "Profile", "RoleAssignment", "ScopeKind", "User"]


class User(AbstractUser):
    """Application user.

    A custom model from the start: swapping the user model after the first migration is
    very costly. Profiles and scopes live in ``RoleAssignment``.
    """


class AuditQuerySet(models.QuerySet):
    """Queryset that refuses bulk updates and deletes: the audit log is append-only."""

    def update(self, **kwargs):
        """Refuse bulk updates.

        Raises:
            PermissionError: always.
        """
        raise PermissionError("Audit entries cannot be modified.")

    def delete(self):
        """Refuse bulk deletes.

        Raises:
            PermissionError: always.
        """
        raise PermissionError("Audit entries cannot be deleted.")

    def bulk_create(self, objs, *args, **kwargs):
        """Insert entries in bulk, refusing upserts that would overwrite existing ones.

        Raises:
            PermissionError: if ``update_conflicts`` is requested.
        """
        if kwargs.get("update_conflicts"):
            raise PermissionError("Audit entries cannot be modified.")
        return super().bulk_create(objs, *args, **kwargs)


class AuditEntry(models.Model):
    """One audited change to business data: who, when, previous value, new value and reason.

    Append-only: existing entries cannot be saved again or deleted through the ORM
    (an extra database-level guard is a possible later hardening). Written by
    ``apps.core.audit`` in the same transaction as the change itself.
    """

    class Action(models.TextChoices):
        """Kind of change recorded."""

        CREATE = "create", _("criação")
        UPDATE = "update", _("alteração")
        DELETE = "delete", _("eliminação")

    actor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("autor"),
        help_text=_("Who made the change; empty only for system actions."),
    )
    created_at = models.DateTimeField(
        _("data e hora"), auto_now_add=True, help_text=_("When the change was made.")
    )
    entity = models.CharField(
        _("entidade"),
        max_length=100,
        help_text=_("Model label of the changed record, e.g. 'core.roleassignment'."),
    )
    entity_id = models.CharField(
        _("identificador da entidade"),
        max_length=64,
        help_text=_("Primary key of the changed record, as text."),
    )
    action = models.CharField(
        _("ação"), max_length=8, choices=Action.choices, help_text=_("Kind of change.")
    )
    old_value = models.JSONField(
        _("valor anterior"),
        null=True,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_("Field values before the change; empty on creation."),
    )
    new_value = models.JSONField(
        _("valor novo"),
        null=True,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_("Field values after the change; empty on deletion."),
    )
    reason = models.TextField(
        _("motivo"), blank=True, help_text=_("Why it was changed; required for update and delete.")
    )

    objects = AuditQuerySet.as_manager()

    class Meta:
        verbose_name = _("registo de auditoria")
        verbose_name_plural = _("registos de auditoria")
        ordering = ["-created_at", "-id"]
        # Django uses the base manager for related access; make it the guarded one too.
        base_manager_name = "objects"
        indexes = [
            # Look up the history of one record.
            models.Index(fields=["entity", "entity_id"], name="audit_entity_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.entity}#{self.entity_id} {self.action}"

    def save(self, *args, **kwargs):
        """Insert a new entry; refuse to change an existing one.

        Raises:
            PermissionError: if the entry already exists.
        """
        if (
            not self._state.adding
            or kwargs.get("force_update")
            or kwargs.get("update_fields") is not None
        ):
            raise PermissionError("Audit entries cannot be modified.")
        # Always INSERT: a new object carrying an existing id (or a loaded entry with a
        # forced 'adding' flag) would otherwise be saved as an UPDATE of that row.
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Refuse deletion.

        Raises:
            PermissionError: always.
        """
        raise PermissionError("Audit entries cannot be deleted.")


class RoleAssignment(models.Model):
    """One profile held by a user over one scope.

    A user may have several assignments (for example coordinator of one coordination and
    teacher of their own record). The PGC manager acts on every Faculty assigned to them,
    one assignment per Faculty. Permission checks are built on top of this in T1.2.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="role_assignments",
        verbose_name=_("utilizador"),
        help_text=_("User holding the profile."),
    )
    profile = models.CharField(
        _("perfil"), max_length=32, choices=Profile.choices, help_text=_("Profile held.")
    )
    scope_kind = models.CharField(
        _("tipo de âmbito"),
        max_length=16,
        choices=ScopeKind.choices,
        help_text=_("What scope_id refers to; 'none' when the profile has no scope."),
    )
    scope_id = models.PositiveBigIntegerField(
        _("identificador do âmbito"),
        null=True,
        blank=True,
        help_text=_("Id of the Faculty, coordination or teacher; empty only for 'none'."),
    )

    class Meta:
        verbose_name = _("atribuição de perfil")
        verbose_name_plural = _("atribuições de perfil")
        constraints = [
            # No duplicate (user, profile, scope); nulls_distinct=False so that two unscoped
            # assignments (NULL scope_id) also count as duplicates.
            models.UniqueConstraint(
                fields=["user", "profile", "scope_kind", "scope_id"],
                nulls_distinct=False,
                name="unique_role_assignment",
            ),
            # scope_id is present exactly when there is a scope.
            models.CheckConstraint(
                condition=(
                    models.Q(scope_kind=ScopeKind.NONE, scope_id__isnull=True)
                    | (~models.Q(scope_kind=ScopeKind.NONE) & models.Q(scope_id__isnull=False))
                ),
                name="role_assignment_scope_id_matches_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} – {self.get_profile_display()}"

    def clean(self) -> None:
        """Check that the profile admits the chosen scope kind.

        Raises:
            ValidationError: if the specification fixes a different scope kind for the profile.
        """
        if not scope_kind_allowed(self.profile, self.scope_kind):
            raise ValidationError({"scope_kind": _("Este perfil não admite este tipo de âmbito.")})
