"""Server-side permission checks: which profiles may perform which actions, and on what scope.

Implements: docs/especificacao/07_arquitetura.md – Permissions (always checked on the server).
Pure domain module: no dependency on views or templates. See D38, D39 and D69.

Only rules the specification states unambiguously are registered here. Each feature
registers its own actions when it is built; the specification has no complete
profile-by-action matrix, and none is invented.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db.models import Q

from .roles import Profile, ScopeKind
from .scopes import ScopeNotFound, faculty_of_scope, scope_ids_in_faculties

# Profiles that never write (specification: viewer is read-only; the teacher only reads
# their own distribution).
READ_ONLY_PROFILES = frozenset({Profile.VIEWER, Profile.TEACHER})

# Which kind of assignment lets a profile act on the data of a coordination (D69):
# the coordinator only through their own coordination, the Executive Board and the PGC manager
# through the Faculty the coordination belongs to. No other profile ever covers a coordination.
COORDINATION_COVER: dict[str, str] = {
    Profile.COORDINATOR: ScopeKind.COORDINATION,
    Profile.EXECUTIVE_BOARD: ScopeKind.FACULTY,
    Profile.PGC_MANAGER: ScopeKind.FACULTY,
}


@dataclass(frozen=True)
class Action:
    """A permission-controlled action.

    Attributes:
        code: unique identifier such as ``"room.edit"``.
        profiles: profiles allowed to perform it.
        write: whether the action changes data.
        scoped: whether the action targets a scope (coordination, Faculty...). A scoped
            action can only be checked together with its target scope.
    """

    code: str
    profiles: frozenset[str]
    write: bool
    scoped: bool = False


class PermissionRegistry:
    """Registry of actions and the check that decides whether a user may perform one."""

    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(
        self, code: str, profiles: set[str], *, write: bool, scoped: bool = False
    ) -> Action:
        """Define an action and the profiles that may perform it.

        Args:
            code: unique action code.
            profiles: profiles allowed to perform the action.
            write: True if the action changes data.
            scoped: True if the action targets a scope and must be checked against it.

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
        action = Action(code, frozenset(profiles), write, scoped)
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

        For an unscoped action any assignment with an allowed profile qualifies. A scoped
        action must be checked against its target: the assignment must have exactly that
        scope kind and id. The Faculty-covers-coordination hierarchy is deliberately not
        here: use ``can_on_coordination`` for data that belongs to a coordination (D69).
        Omitting the scope is never read as "any scope".

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
            ImproperlyConfigured: if a scoped action is checked without a scope.
        """
        try:
            action = self._actions[code]
        except KeyError:
            raise LookupError(f"Unknown action: {code}") from None
        if action.scoped and scope_kind is None:
            raise ImproperlyConfigured(f"Scoped action checked without a scope: {code}")
        if not (user.is_authenticated and user.is_active):
            return False
        assignments = user.role_assignments.filter(profile__in=action.profiles)
        if scope_kind is not None:
            assignments = assignments.filter(scope_kind=scope_kind, scope_id=scope_id)
        return assignments.exists()

    def scope_ids(self, user, code: str, scope_kind: str) -> set[int]:
        """Return the ids of the scopes of one kind where the user may perform an action.

        Used to filter lists and to limit the choices of a form to what the user manages.

        Args:
            user: the requesting user (may be anonymous).
            code: action code.
            scope_kind: kind of scope, e.g. ``ScopeKind.FACULTY``.

        Returns:
            The scope ids; empty for anonymous or inactive users and when none applies.

        Raises:
            LookupError: if the action is not registered (fail closed).
        """
        try:
            action = self._actions[code]
        except KeyError:
            raise LookupError(f"Unknown action: {code}") from None
        if not (user.is_authenticated and user.is_active):
            return set()
        ids = user.role_assignments.filter(
            profile__in=action.profiles, scope_kind=scope_kind
        ).values_list("scope_id", flat=True)
        return {i for i in ids if i is not None}

    # --- coordination scope (D69) ---------------------------------------------------------

    def _action(self, code: str) -> Action:
        """Return a registered action, failing closed on an unknown code."""
        try:
            return self._actions[code]
        except KeyError:
            raise LookupError(f"Unknown action: {code}") from None

    def _scoped_action(self, code: str) -> Action:
        """Return a registered action that must be scoped, as every coordination check needs."""
        action = self._action(code)
        if not action.scoped:
            raise ImproperlyConfigured(f"Coordination check on an unscoped action: {code}")
        return action

    @staticmethod
    def _is_active(user) -> bool:
        """Tell whether the user is authenticated and has an enabled account."""
        return bool(user.is_authenticated and user.is_active)

    def can_on_coordination(self, user, code: str, coordination_id: int | None) -> bool:
        """Tell whether a user may perform a scoped action on data of one coordination.

        The coordinator needs an assignment to that coordination; the Executive Board and the
        PGC manager need an assignment to the Faculty the coordination belongs to; no other
        profile covers a coordination (``COORDINATION_COVER``, D69). The action must also admit
        the profile. The Faculty is read at check time, so moving a coordination to another
        Faculty moves the access with it (D62).

        Args:
            user: the requesting user (may be anonymous).
            code: code of a scoped action.
            coordination_id: id of the coordination that owns the data.

        Returns:
            True only for an active, authenticated user covering the coordination. A missing
            or unknown coordination gives False (fail closed); ``is_superuser`` gives no pass.

        Raises:
            LookupError: if the action is not registered.
            ImproperlyConfigured: if the action is not scoped.
        """
        action = self._scoped_action(code)
        if coordination_id is None or not self._is_active(user):
            return False
        try:
            faculty_id = faculty_of_scope(ScopeKind.COORDINATION, coordination_id)
        except ScopeNotFound:
            return False
        covers = Q()
        if Profile.COORDINATOR in action.profiles:
            covers |= Q(
                profile=Profile.COORDINATOR,
                scope_kind=ScopeKind.COORDINATION,
                scope_id=coordination_id,
            )
        faculty_profiles = action.profiles & {Profile.EXECUTIVE_BOARD, Profile.PGC_MANAGER}
        if faculty_profiles:
            covers |= Q(
                profile__in=faculty_profiles, scope_kind=ScopeKind.FACULTY, scope_id=faculty_id
            )
        if not covers:
            return False
        return user.role_assignments.filter(covers).exists()

    def require_on_coordination(self, user, code: str, coordination_id: int | None) -> None:
        """Like ``can_on_coordination`` but raise on denial.

        Raises:
            PermissionDenied: if the user does not cover the coordination (HTTP 403).
            LookupError: if the action is not registered.
            ImproperlyConfigured: if the action is not scoped.
        """
        if not self.can_on_coordination(user, code, coordination_id):
            raise PermissionDenied(f"Not allowed: {code}")

    def coordination_ids(self, user, code: str) -> set[int]:
        """Return the ids of the coordinations on which a user may perform a scoped action.

        Used to filter lists and to limit form choices. It agrees with ``can_on_coordination``:
        the coordinator's own coordinations plus every coordination of the Faculties held by an
        Executive Board member or a PGC manager (D69).

        Args:
            user: the requesting user (may be anonymous).
            code: code of a scoped action.

        Returns:
            The coordination ids; empty for anonymous or inactive users.

        Raises:
            LookupError: if the action is not registered.
            ImproperlyConfigured: if the action is not scoped.
        """
        action = self._scoped_action(code)
        if not self._is_active(user):
            return set()
        rows = user.role_assignments.filter(
            profile__in=action.profiles & COORDINATION_COVER.keys()
        ).values_list("profile", "scope_kind", "scope_id")
        direct: set[int] = set()
        faculties: set[int] = set()
        for profile, kind, scope_id in rows:
            if scope_id is None or kind != COORDINATION_COVER[profile]:
                continue  # an assignment of the wrong kind covers nothing
            (direct if kind == ScopeKind.COORDINATION else faculties).add(scope_id)
        if faculties:
            direct |= scope_ids_in_faculties(ScopeKind.COORDINATION, faculties)
        return direct

    def own_teacher_ids(self, user, code: str) -> set[int]:
        """Return the ids of the teacher records linked to the user's own account (D09).

        Args:
            user: the requesting user (may be anonymous).
            code: action code; the teacher profile must be allowed to perform it.

        Returns:
            The teacher ids; empty unless the user holds a teacher assignment and the action
            admits the teacher profile. Since the teacher never writes, only read actions do.

        Raises:
            LookupError: if the action is not registered.
        """
        action = self._action(code)
        if Profile.TEACHER not in action.profiles or not self._is_active(user):
            return set()
        ids = user.role_assignments.filter(
            profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER
        ).values_list("scope_id", flat=True)
        return {i for i in ids if i is not None}

    def can_on_teacher(self, user, code: str, teacher) -> bool:
        """Tell whether a user may perform a scoped action on a teacher's data.

        True for the teacher's own record (D09) or for whoever covers the teacher's
        coordination. Pass a teacher loaded from the database, never one built from submitted
        form data, because the coordination decides the answer.

        Args:
            user: the requesting user (may be anonymous).
            code: code of a scoped action.
            teacher: an object with ``pk`` and ``coordination_id``.

        Returns:
            True if the teacher is the user's own record or the user covers their coordination.

        Raises:
            LookupError: if the action is not registered.
            ImproperlyConfigured: if the action is not scoped.
        """
        self._scoped_action(code)
        if teacher.pk in self.own_teacher_ids(user, code):
            return True
        return self.can_on_coordination(user, code, teacher.coordination_id)

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
            ImproperlyConfigured: if a scoped action is checked without a scope.
        """
        if not self.can(user, code, scope_kind, scope_id):
            raise PermissionDenied(f"Not allowed: {code}")


registry = PermissionRegistry()

# Rules stated unambiguously in docs/especificacao/02_perfis_e_dados.md.
registry.register("room.edit", {Profile.FACILITIES}, write=True)  # Património enters rooms
# Reading the room lookup: the coordinator, Consulta and Património (D64); no scope.
registry.register(
    "room.view", {Profile.COORDINATOR, Profile.VIEWER, Profile.FACILITIES}, write=False
)
# Room types are configured by Património too; rooms are University-wide, so no scope (D63).
registry.register("room_type.edit", {Profile.FACILITIES}, write=True)
registry.register("enrollment.edit", {Profile.ACADEMIC_SERVICES}, write=True)  # enrollments
# The PGC manager configures the class types (D45).
registry.register("class_type.edit", {Profile.PGC_MANAGER}, write=True)
# The PGC manager declares cross-course subjects; a group needs scope over every member's
# Faculty (D06, D22, D55).
registry.register("cross_course_subject.edit", {Profile.PGC_MANAGER}, write=True, scoped=True)
# Teachers (scoped to the Faculty of their coordination), their positions and categories (D56).
registry.register("teacher.edit", {Profile.PGC_MANAGER}, write=True, scoped=True)
registry.register("position.edit", {Profile.PGC_MANAGER}, write=True)
registry.register("category.edit", {Profile.PGC_MANAGER}, write=True)
# Accounts and roles: the manager acts only on the Faculties assigned to them (D62).
registry.register("account.edit", {Profile.PGC_MANAGER}, write=True, scoped=True)
# System parameters (weeks per semester...) are University-wide: no scope (D60).
registry.register("parameter.edit", {Profile.PGC_MANAGER}, write=True)
# Hours ranges are the same for the whole University, so the action has no scope (D58).
registry.register("load_range.edit", {Profile.PGC_MANAGER}, write=True)
# The PGC manager creates the turmas, only in the Faculties assigned to them (D49, D54).
registry.register("class_group.edit", {Profile.PGC_MANAGER}, write=True, scoped=True)
# Faculties and academic years are not limited to a Faculty: any PGC manager (D50, to confirm).
registry.register("faculty.edit", {Profile.PGC_MANAGER}, write=True)
registry.register("academic_year.edit", {Profile.PGC_MANAGER}, write=True)
# Coordinations and courses: the manager acts only on the Faculties assigned to them (D51).
registry.register("coordination.edit", {Profile.PGC_MANAGER}, write=True, scoped=True)
registry.register("course.edit", {Profile.PGC_MANAGER}, write=True, scoped=True)
registry.register("study_plan.edit", {Profile.PGC_MANAGER}, write=True, scoped=True)
registry.register("subject.edit", {Profile.PGC_MANAGER}, write=True, scoped=True)


def can(user, code: str, scope_kind: str | None = None, scope_id: int | None = None) -> bool:
    """Shortcut for ``registry.can``."""
    return registry.can(user, code, scope_kind, scope_id)


def require(user, code: str, scope_kind: str | None = None, scope_id: int | None = None) -> None:
    """Shortcut for ``registry.require``."""
    registry.require(user, code, scope_kind, scope_id)


def can_on_coordination(user, code: str, coordination_id: int | None) -> bool:
    """Shortcut for ``registry.can_on_coordination``."""
    return registry.can_on_coordination(user, code, coordination_id)


def require_on_coordination(user, code: str, coordination_id: int | None) -> None:
    """Shortcut for ``registry.require_on_coordination``."""
    registry.require_on_coordination(user, code, coordination_id)


def coordination_ids_for(user, code: str) -> set[int]:
    """Shortcut for ``registry.coordination_ids``."""
    return registry.coordination_ids(user, code)


__all__ = [
    "COORDINATION_COVER",
    "Action",
    "PermissionRegistry",
    "ScopeKind",
    "can",
    "can_on_coordination",
    "coordination_ids_for",
    "registry",
    "require",
    "require_on_coordination",
]
