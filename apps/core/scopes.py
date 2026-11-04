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


def register_scope(kind: str, resolver: Callable[[int], int]) -> None:
    """Register how to find the Faculty of a scope kind.

    Args:
        kind: a ``ScopeKind`` value.
        resolver: a function from the scope id to the Faculty id; it raises ``ScopeNotFound``
            if the id names no record.
    """
    _RESOLVERS[kind] = resolver


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
