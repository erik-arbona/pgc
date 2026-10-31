"""Models of ``core``: user and role assignments (profile + scope).

Implements: docs/especificacao/07_arquitetura.md – Permissions (profile and scope per user).
Audit models arrive with T1.3.
"""

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .roles import Profile, ScopeKind, scope_kind_allowed

__all__ = ["Profile", "RoleAssignment", "ScopeKind", "User"]


class User(AbstractUser):
    """Application user.

    A custom model from the start: swapping the user model after the first migration is
    very costly. Profiles and scopes live in ``RoleAssignment``.
    """


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
