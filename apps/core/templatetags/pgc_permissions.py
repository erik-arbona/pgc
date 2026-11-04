"""Template tag to hide links the user may not use.

Implements: docs/especificacao/07_arquitetura.md – permissions. Hiding a link is only
cosmetic: the server still checks the permission on every request.
"""

from __future__ import annotations

from django import template

from apps.core.permissions import can as can_perform
from apps.core.permissions import registry

register = template.Library()


@register.simple_tag(takes_context=True)
def can(context, code: str, scope_kind: str | None = None, scope_id: int | None = None) -> bool:
    """Return whether the current user may perform an action.

    Usage: ``{% can "class_type.edit" as allowed %}{% if allowed %}...{% endif %}``.

    Args:
        context: template context (provides ``request``).
        code: registered action code.
        scope_kind: scope kind for scoped actions.
        scope_id: scope id for scoped actions.

    Returns:
        True if allowed; False for anonymous users.
    """
    return can_perform(context["request"].user, code, scope_kind, scope_id)


@register.simple_tag(takes_context=True)
def has_scope(context, code: str, scope_kind: str) -> bool:
    """Return whether the user may perform a scoped action on at least one scope.

    Usage: ``{% has_scope "course.edit" "faculty" as allowed %}``.

    Args:
        context: template context (provides ``request``).
        code: registered scoped action code.
        scope_kind: scope kind, e.g. ``"faculty"``.

    Returns:
        True if the user holds an allowed profile on some scope of that kind.
    """
    return bool(registry.scope_ids(context["request"].user, code, scope_kind))
