"""Account services: create accounts and assign roles, audited and limited by scope.

Implements: docs/especificacao/03_requisitos_funcionais.md – accounts by profile managed by the
PGC manager; D38, D39, D51, D62. Every function checks the authority of the actor on the server.

Rules that stop a manager from gaining power they should not have:
- roles are granted only over Faculties the actor manages, and only the profiles the
  specification gives a scope to (D62); the rest are granted by the operator command;
- an account is edited or deactivated only if every role it holds is inside the actor's
  Faculties; administrator accounts (superuser or staff) and accounts with roles that have no
  Faculty are out of reach;
- nobody changes their own account, so there is neither self-escalation nor self-lock-out;
- the interface never sets a password: accounts are created with an unusable one.
"""

from __future__ import annotations

import unicodedata

from django.contrib.auth import get_user_model
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from .audit import audited_delete, audited_save
from .models import RoleAssignment
from .permissions import registry
from .roles import REQUIRED_SCOPE_KIND, Profile, ScopeKind, scope_kind_allowed
from .scopes import ScopeNotFound, faculty_of_scope, scope_ids_in_faculties, scope_options

ACTION = "account.edit"

# Profiles whose scope the specification fixes; a manager may grant only these. Serviços
# Académicos, Património and Consulta have no defined scope, so only the operator grants them.
GRANTABLE_PROFILES = frozenset(
    {Profile.PGC_MANAGER, Profile.COORDINATOR, Profile.EXECUTIVE_BOARD, Profile.TEACHER}
)


def _managed_faculties(actor) -> set[int]:
    """Return the Faculties on which the actor may manage accounts."""
    return registry.scope_ids(actor, ACTION, ScopeKind.FACULTY)


def _faculty_of(assignment: RoleAssignment) -> int | None:
    """Return the Faculty of a role, or ``None`` if it has none or points at nothing."""
    try:
        return faculty_of_scope(assignment.scope_kind, assignment.scope_id)
    except ScopeNotFound:
        return None


def can_manage_account(actor, target) -> bool:
    """Tell whether the actor may edit or deactivate an account.

    Args:
        actor: the user acting.
        target: the account.

    Returns:
        True only if the actor manages at least one Faculty, is not the target, the target is
        not an administrator, and every role of the target is inside the actor's Faculties.
        An account with no roles may be managed by any manager.
    """
    if actor.pk == target.pk or target.is_superuser or target.is_staff:
        return False
    faculties = _managed_faculties(actor)
    if not faculties:
        return False
    for assignment in target.role_assignments.all():
        faculty_id = _faculty_of(assignment)
        if faculty_id is None or faculty_id not in faculties:
            return False
    return True


def visible_accounts(actor):
    """Return the accounts a manager sees in the list.

    These are the accounts with no roles and those with at least one role inside the actor's
    Faculties. The actor themselves and the administrators are left out. An account that also has
    roles elsewhere is listed but cannot be managed (``can_manage_account``).

    Args:
        actor: the user acting.

    Returns:
        A queryset of users ordered by username (empty if the actor manages no Faculty).
    """
    user_model = get_user_model()
    faculties = _managed_faculties(actor)
    if not faculties:
        return user_model.objects.none()
    inside = Q(role_assignments__isnull=True)
    for kind in (ScopeKind.FACULTY, ScopeKind.COORDINATION, ScopeKind.TEACHER):
        ids = scope_ids_in_faculties(kind, faculties)
        inside |= Q(role_assignments__scope_kind=kind, role_assignments__scope_id__in=ids)
    return (
        user_model.objects.filter(inside)
        .exclude(pk=actor.pk)
        .exclude(is_superuser=True)
        .exclude(is_staff=True)
        .distinct()
        .order_by("username")
        .prefetch_related("role_assignments")
    )


def _require_manage(actor, target) -> None:
    """Raise ``PermissionDenied`` unless the actor may manage the target account."""
    if not can_manage_account(actor, target):
        raise PermissionDenied("Not allowed to manage this account.")


def create_account(
    actor, *, username: str, first_name: str, last_name: str, email: str, reason: str = ""
):
    """Create an account with an unusable password (the interface never sets one, D62).

    Args:
        actor: the user creating it; must manage at least one Faculty.
        username: the login name; unique ignoring case and never changed afterwards.
        first_name: given name.
        last_name: family name.
        email: e-mail address.
        reason: optional reason (D40).

    Returns:
        The new user.

    Raises:
        PermissionDenied: if the actor manages no Faculty.
        ValidationError: if the username is empty or already in use.
    """
    if not _managed_faculties(actor):
        raise PermissionDenied("Not allowed to create accounts.")
    # NFKC makes look-alike characters (full-width letters, combining marks) collide with the
    # plain ones; the validator then rejects spaces, zero-width characters and markup. Audited
    # saves do not run model validation, so both are applied here.
    username = unicodedata.normalize("NFKC", username.strip())
    if not username:
        raise ValidationError({"username": _("Indique o nome de utilizador.")})
    try:
        UnicodeUsernameValidator()(username)
    except ValidationError:
        raise ValidationError(
            {"username": _("Use só letras, números e os caracteres @ . + - _ .")}
        ) from None
    if len(username) > 150:
        raise ValidationError({"username": _("Use no máximo 150 caracteres.")})
    user_model = get_user_model()
    if user_model.objects.filter(username__iexact=username).exists():
        raise ValidationError({"username": _("Já existe uma conta com este nome de utilizador.")})
    user = user_model(username=username, first_name=first_name, last_name=last_name, email=email)
    user.set_unusable_password()
    audited_save(user, actor, reason)
    return user


def create_account_with_role(
    actor,
    *,
    username: str,
    first_name: str,
    last_name: str,
    email: str,
    profile: str,
    scope_kind: str,
    scope_id: int | None,
    reason: str = "",
):
    """Create an account and its first role in one transaction (D62).

    Used to give a teacher an account from the teacher list. If the role is refused (for
    example a teacher of another Faculty), nothing is created, not even the account.

    Returns:
        The new user.

    Raises:
        PermissionDenied, ValidationError: as ``create_account`` and ``assign_role``.
    """
    with transaction.atomic():
        user = create_account(
            actor,
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            reason=reason,
        )
        assign_role(actor, user, profile, scope_kind, scope_id, reason)
        return user


def update_account(actor, user, *, first_name: str, last_name: str, email: str, reason: str):
    """Change the names and e-mail of an account; the username never changes.

    Raises:
        PermissionDenied: if the actor may not manage the account.
        ValidationError: if the reason is missing and something changed.
    """
    _require_manage(actor, user)
    values = {"first_name": first_name, "last_name": last_name, "email": email}
    if all(getattr(user, field) == value for field, value in values.items()):
        return user
    previous = {field: getattr(user, field) for field in values}
    for field, value in values.items():
        setattr(user, field, value)
    try:
        audited_save(user, actor, reason)
    except ValidationError:
        # Leave the in-memory object as it was, so a retry with a reason still saves.
        for field, value in previous.items():
            setattr(user, field, value)
        raise
    return user


def set_active(actor, user, active: bool, reason: str):
    """Activate or deactivate an account; deactivation is how an account ends (D62).

    Raises:
        PermissionDenied: if the actor may not manage the account.
        ValidationError: if the reason is missing.
    """
    _require_manage(actor, user)
    if user.is_active == active:
        return user
    user.is_active = active
    try:
        audited_save(user, actor, reason)
    except ValidationError:
        user.is_active = not active  # unchanged in memory, so a retry with a reason still saves
        raise
    return user


def assign_role(
    actor, user, profile: str, scope_kind: str, scope_id: int | None, reason: str = ""
) -> RoleAssignment:
    """Grant a role to an account, over a scope the actor manages.

    Args:
        actor: the user granting; must manage the Faculty of the scope.
        user: the account receiving the role.
        profile: a profile the specification gives a scope to (``GRANTABLE_PROFILES``).
        scope_kind: the scope kind the profile requires.
        scope_id: the id of the record the scope names; it must exist.
        reason: optional reason (D40).

    Returns:
        The new role assignment.

    Raises:
        PermissionDenied: for a self-grant, an administrator account, a profile managers may
            not grant, or a scope outside the actor's Faculties.
        ValidationError: for a scope kind the profile does not admit, a scope that names
            nothing, a duplicate role, or a teacher who already has an account.
    """
    if actor.pk == user.pk or user.is_superuser or user.is_staff:
        raise PermissionDenied("Not allowed to grant roles to this account.")
    if profile not in GRANTABLE_PROFILES:
        raise PermissionDenied("Only the operator grants this profile.")
    if scope_kind == ScopeKind.NONE or not scope_kind_allowed(profile, scope_kind):
        raise ValidationError({"scope_kind": _("Este perfil não admite este tipo de âmbito.")})
    try:
        faculty_id = faculty_of_scope(scope_kind, scope_id)
    except ScopeNotFound:
        raise ValidationError({"scope_id": _("O âmbito indicado não existe.")}) from None
    if faculty_id not in _managed_faculties(actor):
        raise PermissionDenied("Not allowed to grant roles over this Faculty.")
    if RoleAssignment.objects.filter(
        user=user, profile=profile, scope_kind=scope_kind, scope_id=scope_id
    ).exists():
        raise ValidationError(_("Esta conta já tem este perfil neste âmbito."))
    if (
        profile == Profile.TEACHER
        and RoleAssignment.objects.filter(
            profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER, scope_id=scope_id
        ).exists()
    ):
        raise ValidationError(_("Este docente já tem uma conta."))
    role = RoleAssignment(user=user, profile=profile, scope_kind=scope_kind, scope_id=scope_id)
    try:
        with transaction.atomic():
            audited_save(role, actor, reason)
    except IntegrityError:
        # Another request won the race; the database constraints are the real guard.
        if profile == Profile.TEACHER:
            raise ValidationError(_("Este docente já tem uma conta.")) from None
        raise ValidationError(_("Esta conta já tem este perfil neste âmbito.")) from None
    return role


def can_revoke_role(actor, assignment: RoleAssignment) -> bool:
    """Tell whether the actor may remove a role.

    Args:
        actor: the user acting.
        assignment: the role.

    Returns:
        True only if the role is not the actor's own, does not belong to an administrator
        account, and its scope belongs to a Faculty the actor manages. Roles without a Faculty
        (viewer, facilities...) are operator-only.
    """
    holder = assignment.user
    if holder.pk == actor.pk or holder.is_superuser or holder.is_staff:
        return False
    faculty_id = _faculty_of(assignment)
    return faculty_id is not None and faculty_id in _managed_faculties(actor)


def revoke_role(actor, assignment: RoleAssignment, reason: str) -> None:
    """Remove a role the actor manages.

    Raises:
        PermissionDenied: if ``can_revoke_role`` says no.
        ValidationError: if the reason is missing.
    """
    if not can_revoke_role(actor, assignment):
        raise PermissionDenied("Not allowed to revoke this role.")
    audited_delete(assignment, actor, reason)


def grantable_scope_options(actor, profile: str | None = None) -> list[tuple[str, str]]:
    """Return the scopes the actor could grant, as ``("kind:id", label)`` pairs for a select.

    Only scopes inside the actor's Faculties are offered. A teacher who already has an account
    is left out. With a profile, only the scope kind that profile requires is listed (and
    nothing for a profile managers may not grant). The server checks every grant again.

    Args:
        actor: the user acting.
        profile: a profile value to filter by, or ``None`` for all grantable kinds.

    Returns:
        The options, grouped by kind in the order Faculty, coordination, teacher.
    """
    faculties = _managed_faculties(actor)
    kinds = [ScopeKind.FACULTY, ScopeKind.COORDINATION, ScopeKind.TEACHER]
    if profile is not None:
        required = REQUIRED_SCOPE_KIND.get(profile)
        kinds = [required] if profile in GRANTABLE_PROFILES and required in kinds else []
    linked = set(
        RoleAssignment.objects.filter(
            profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER
        ).values_list("scope_id", flat=True)
    )
    options: list[tuple[str, str]] = []
    for kind in kinds:
        for scope_id, label in scope_options(kind, faculties):
            if kind == ScopeKind.TEACHER and scope_id in linked:
                continue
            options.append((f"{kind}:{scope_id}", f"{ScopeKind(kind).label}: {label}"))
    return options
