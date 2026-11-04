"""The mixin that makes DSD models refuse writes outside ``dsd_write`` (T2.2).

Implements: docs/backlog_fase2.md T2.2; D43, D86. It lives apart from ``lifecycle`` so that the
models can inherit it without importing the models that ``lifecycle`` needs.
"""

from __future__ import annotations

from contextvars import ContextVar

from django.core.exceptions import ImproperlyConfigured

# The cell (semester id, coordination id) the current code is allowed to write.
_ACTIVE: ContextVar[tuple[int, int] | None] = ContextVar("dsd_active_cell", default=None)


class GuardedDsdWrites:
    """Mixin for the DSD models that hold data of a semester and a coordination.

    List it before ``models.Model`` in the bases and implement ``dsd_cell``. ``save`` and
    ``delete`` then refuse to run outside ``dsd_write`` for the same cell, so a write that skips
    the state check fails loudly instead of silently ignoring a closed semester (D43).
    """

    def dsd_cell(self) -> tuple[int, int]:
        """Return ``(dsd_semester_id, coordination_id)`` of the data this record holds."""
        raise NotImplementedError

    def assert_write_allowed(self) -> None:
        """Raise unless the current code runs inside ``dsd_write`` for this record's cell."""
        if _ACTIVE.get() != self.dsd_cell():
            raise ImproperlyConfigured(
                "DSD data must be written inside dsd_write() for its semester and coordination."
            )

    def save(self, *args, **kwargs):
        """Save the record, only inside ``dsd_write`` for its cell."""
        self.assert_write_allowed()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Delete the record, only inside ``dsd_write`` for its cell."""
        self.assert_write_allowed()
        return super().delete(*args, **kwargs)
