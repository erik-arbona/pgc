"""View mixins that enforce permissions on the server.

Implements: docs/especificacao/07_arquitetura.md – Permissions (never only in the interface).
"""

from __future__ import annotations

from .permissions import require


class PermissionRequiredMixin:
    """Deny the request (HTTP 403) unless the user may perform ``permission_action``.

    Set ``permission_action`` on the view. Override ``get_permission_scope`` for actions that
    depend on the object being acted on (for example the coordination of the URL).
    """

    permission_action: str = ""

    def get_permission_scope(self) -> tuple[str | None, int | None]:
        """Return the ``(scope_kind, scope_id)`` the action applies to; ``(None, None)`` if none."""
        return None, None

    def dispatch(self, request, *args, **kwargs):
        """Check the permission before running any handler (GET, POST, ...).

        Raises:
            PermissionDenied: if the user lacks the permission.
        """
        scope_kind, scope_id = self.get_permission_scope()
        require(request.user, self.permission_action, scope_kind, scope_id)
        return super().dispatch(request, *args, **kwargs)
