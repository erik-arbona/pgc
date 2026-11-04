"""Server-side permission checks: which profiles may perform which actions, and on what scope.

Implements: docs/especificacao/07_arquitetura.md – Permissions (always checked on the server).
Pure domain module: no dependency on views or templates. See D38 and D39.

Only rules the specification states unambiguously are registered here. Each feature
registers its own actions when it is built; the specification has no complete
profile-by-action matrix, and none is invented.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from .roles import Profile, ScopeKind

# Profiles that never write (specification: viewer is read-only; the teacher only reads
# their own distribution).
READ_ONLY_PROFILES = frozenset({Profile.VIEWER, Profile.TEACHER})


@dataclass(frozen=True)
class Action:
    """A permission-controlled action.

    Attributes:
        code: unique identifier such as ``"room.edit"``.
        profiles: profiles allowed to perform it.
        write: whether the action changes data.
    """

    code: str
    profiles: frozenset[str]
    write: bool


class PermissionRegistry:
    """Registry of actions and the check that decides whether a user may perform one."""

    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, code: str, profiles: set[str], *, write: bool) -> Action:
        """Define an action and the profiles that may perform it.

        Args:
            code: unique action code.
            profiles: profiles allowed to perform the action.
            write: True if the action changes data.

        Returns:
            The registered action.

        Raises:
            ValueError: if the code is already registered, or a write action is granted to a
                read-only profile (viewer, teacher).
        """
        if code in self._actions:
            raise ValueError(f"Action already registered: {code}")
        if write and READ_ONLY_PROFILES & set(profiles):
            raise ValueError(f"Read-only profiles cannot be granted a write action: {code}")
        action = Action(code, frozenset(profiles), write)
        self._actions[code] = action
        return action

    def can(
        self,
        user,
        code: str,
        scope_kind: str | None = None,
        scope_id: int | None = None,
    ) -> bool:
        """Tell whether a user may perform an action, optionally on a given scope.

        Without a target scope, any assignment with an allowed profile qualifies. With one,
        the assignment must have exactly that scope kind and id (scope hierarchy, such as a
        Faculty covering its coordinations, arrives with T2.1).

        Args:
            user: the requesting user (may be anonymous).
            code: action code.
            scope_kind: kind of the target scope, or None for an unscoped action.
            scope_id: id of the target scope.

        Returns:
            True only for an authenticated, active user holding an allowed profile on the scope.
            ``is_superuser`` gives no pass (D39).

        Raises:
            LookupError: if the action is not registered (fail closed).
        """
        try:
            action = self._actions[code]
        except KeyError:
            raise LookupError(f"Unknown action: {code}") from None
        if not (user.is_authenticated and user.is_active):
            return False
        assignments = user.role_assignments.filter(profile__in=action.profiles)
        if scope_kind is not None:
            assignments = assignments.filter(scope_kind=scope_kind, scope_id=scope_id)
        return assignments.exists()

    def require(
        self,
        user,
        code: str,
        scope_kind: str | None = None,
        scope_id: int | None = None,
    ) -> None:
        """Like ``can`` but raise on denial.

        Raises:
            PermissionDenied: if the user may not perform the action (HTTP 403).
            LookupError: if the action is not registered.
        """
        if not self.can(user, code, scope_kind, scope_id):
            raise PermissionDenied(f"Not allowed: {code}")


registry = PermissionRegistry()

# Rules stated unambiguously in docs/especificacao/02_perfis_e_dados.md.
registry.register("room.edit", {Profile.FACILITIES}, write=True)  # Património enters rooms
registry.register("enrollment.edit", {Profile.ACADEMIC_SERVICES}, write=True)  # enrollments


def can(user, code: str, scope_kind: str | None = None, scope_id: int | None = None) -> bool:
    """Shortcut for ``registry.can``."""
    return registry.can(user, code, scope_kind, scope_id)


def require(user, code: str, scope_kind: str | None = None, scope_id: int | None = None) -> None:
    """Shortcut for ``registry.require``."""
    registry.require(user, code, scope_kind, scope_id)


__all__ = ["Action", "PermissionRegistry", "ScopeKind", "can", "registry", "require"]
