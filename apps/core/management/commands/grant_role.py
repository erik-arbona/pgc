"""Grant a role from the command line (operator only).

Implements: D62. A Django superuser has no business access (D39), so this command is how the
first PGC manager gets in, and the only way to grant the profiles that have no defined scope
(viewer, academic services, facilities). It applies the same checks as the interface except the
list of grantable profiles, and writes to the audit log with no actor (the system).
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.core.audit import audited_save
from apps.core.models import RoleAssignment
from apps.core.roles import Profile, ScopeKind, scope_kind_allowed
from apps.core.scopes import ScopeNotFound, faculty_of_scope


class Command(BaseCommand):
    """Grant a profile to an existing user over a scope."""

    help = "Grant a role: grant_role <username> <profile> <scope_kind> [<scope_id>]"

    def add_arguments(self, parser) -> None:
        """Declare the arguments."""
        parser.add_argument("username")
        parser.add_argument("profile", choices=Profile.values)
        parser.add_argument("scope_kind", choices=ScopeKind.values)
        parser.add_argument("scope_id", nargs="?", type=int, default=None)

    def handle(self, *args, **options) -> None:
        """Validate and save the role.

        Raises:
            CommandError: for an unknown user, a scope kind the profile does not admit, a
                missing or unknown scope id, or a role the user already has.
        """
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=options["username"])
        except user_model.DoesNotExist:
            raise CommandError(f"No user named {options['username']!r}.") from None
        if user.is_superuser or user.is_staff:
            raise CommandError("Administrator accounts take no business roles (D39, D62).")
        profile, kind, scope_id = options["profile"], options["scope_kind"], options["scope_id"]
        if not scope_kind_allowed(profile, kind):
            raise CommandError(f"Profile {profile} does not admit scope kind {kind}.")
        if kind == ScopeKind.NONE:
            if scope_id is not None:
                raise CommandError("A scope of kind 'none' takes no id.")
        else:
            if scope_id is None:
                raise CommandError(f"Scope kind {kind} needs an id.")
            try:
                faculty_of_scope(kind, scope_id)
            except ScopeNotFound as error:
                raise CommandError(str(error)) from None
        if RoleAssignment.objects.filter(
            user=user, profile=profile, scope_kind=kind, scope_id=scope_id
        ).exists():
            raise CommandError("The user already has this role.")
        if (
            profile == Profile.TEACHER
            and RoleAssignment.objects.filter(
                profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER, scope_id=scope_id
            ).exists()
        ):
            raise CommandError("This teacher already has an account.")
        role = RoleAssignment(user=user, profile=profile, scope_kind=kind, scope_id=scope_id)
        try:
            with transaction.atomic():
                audited_save(role, None, "Atribuído pelo operador (linha de comandos)")
        except IntegrityError:
            raise CommandError("The role could not be saved (it already exists).") from None
        self.stdout.write(f"Granted {profile} ({kind} {scope_id}) to {user.username}.")
