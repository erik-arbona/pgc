"""Write guard of the DSD: every write to DSD data goes through the semester state (T2.2).

Implements: docs/backlog_fase2.md T2.2; D43. Future DSD models (offerings, teaching units,
assignments...) inherit ``GuardedDsdWrites`` and every service writes inside ``dsd_write``:

    with dsd_write(user, "dsd.assign", dsd_semester, coordination_id):
        audited_save(assignment, user, reason)

Rules (D86): a closed cell is read-only for everybody; a cell not yet opened accepts writes only
from who may change the state (the PGC manager, who prepares the offerings); an open cell
accepts writes from whoever the action allows for that coordination. The state row is locked
for the duration, so a concurrent closing waits for the write and the next write is refused.
``QuerySet.update`` and ``bulk_*`` skip ``save``: DSD code must not use them.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.permissions import PermissionRegistry, registry

from .lifecycle_rules import CLOSED
from .models import CoordinationSemester, DsdSemester

STATE_EDIT = "dsd.semester_state.edit"

# The cell (semester id, coordination id) the current code is allowed to write.
_ACTIVE: ContextVar[tuple[int, int] | None] = ContextVar("dsd_active_cell", default=None)


@contextmanager
def dsd_write(
    user,
    code: str,
    dsd_semester: DsdSemester,
    coordination_id: int,
    *,
    permission_registry: PermissionRegistry = registry,
) -> Iterator[None]:
    """Allow writes to the DSD data of one semester and coordination, if the state permits.

    Args:
        user: the user writing.
        code: the scoped action that covers the write (checked for the coordination, D69).
        dsd_semester: the semester of the data.
        coordination_id: the coordination that owns the data.
        permission_registry: where ``code`` is registered (the global one by default).

    Raises:
        PermissionDenied: if the user does not cover the coordination for that action.
        ValidationError: if the cell is closed, or not opened and the user cannot change states.
    """
    permission_registry.require_on_coordination(user, code, coordination_id)
    with transaction.atomic():
        cell = (
            CoordinationSemester.objects.select_for_update()
            .select_related("coordination", "dsd_semester__dsd__academic_year")
            .filter(dsd_semester=dsd_semester, coordination_id=coordination_id)
            .first()
        )
        status = None if cell is None else cell.status
        year = dsd_semester.dsd.academic_year.label
        if status == CLOSED:
            raise ValidationError(
                _(
                    "O semestre %(number)s de %(year)s está fechado para esta coordenação: "
                    "só leitura."
                )
                % {"number": dsd_semester.number, "year": year}
            )
        if status is None and not registry.can(user, STATE_EDIT):
            raise ValidationError(
                _("O semestre %(number)s de %(year)s ainda não foi aberto para esta coordenação.")
                % {"number": dsd_semester.number, "year": year}
            )
        token = _ACTIVE.set((dsd_semester.pk, coordination_id))
        try:
            yield
        finally:
            _ACTIVE.reset(token)


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
