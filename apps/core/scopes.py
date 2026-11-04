"""Resolve a scope (kind + numeric id) to the Faculty it belongs to.

Implements: docs/especificacao/07_arquitetura.md – permissions with scope; D38 (a scope is a
kind plus a numeric id, with no foreign key because the target models live in other apps),
D62. The apps that own the target models register a resolver when they start, so ``core`` does
not depend on them. A scope id that names nothing is refused, never read as "some Faculty".
"""

from __future__ import annotations

from collections.abc import Callable

from .roles import ScopeKind


class ScopeNotFound(LookupError):
    """The scope id names no record, or the scope kind has no Faculty."""


_RESOLVERS: dict[str, Callable[[int], int]] = {}
_IN_FACULTIES: dict[str, Callable[[set[int]], set[int]]] = {}
_LABELS: dict[str, Callable[[int], str]] = {}


def register_scope(
    kind: str,
    resolver: Callable[[int], int],
    in_faculties: Callable[[set[int]], set[int]],
    label: Callable[[int], str],
) -> None:
    """Register how to work with a scope kind.

    Args:
        kind: a ``ScopeKind`` value.
        resolver: a function from the scope id to the Faculty id; it raises ``ScopeNotFound``
            if the id names no record.
        in_faculties: a function from a set of Faculty ids to the ids of this kind that belong
            to them (used to list the accounts a manager can see).
        label: a function from the scope id to a name for the interface.
    """
    _RESOLVERS[kind] = resolver
    _IN_FACULTIES[kind] = in_faculties
    _LABELS[kind] = label


def scope_ids_in_faculties(kind: str, faculty_ids: set[int]) -> set[int]:
    """Return the ids of a scope kind that belong to the given Faculties (empty if unknown)."""
    finder = _IN_FACULTIES.get(kind)
    return finder(faculty_ids) if finder else set()


def scope_label(kind: str, scope_id: int | None) -> str:
    """Return a name for a scope, or a dash if it has none or names nothing."""
    namer = _LABELS.get(kind)
    if namer is None or scope_id is None:
        return "—"
    return namer(scope_id)


def faculty_of_scope(kind: str, scope_id: int | None) -> int:
    """Return the id of the Faculty that a scope belongs to.

    Args:
        kind: a ``ScopeKind`` value.
        scope_id: the numeric id of the record the scope refers to.

    Returns:
        The Faculty id.

    Raises:
        ScopeNotFound: if the kind has no Faculty (``none``), has no registered resolver, or
            the id names no record.
    """
    if kind == ScopeKind.NONE or scope_id is None:
        raise ScopeNotFound("A scope of kind 'none' has no Faculty.")
    resolver = _RESOLVERS.get(kind)
    if resolver is None:
        raise ScopeNotFound(f"No resolver registered for scope kind {kind!r}.")
    return resolver(scope_id)
