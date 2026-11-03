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

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.permissions import PermissionRegistry, registry

from .guard import _ACTIVE, GuardedDsdWrites
from .lifecycle_rules import CLOSED
from .models import CoordinationSemester, DsdSemester

__all__ = ["CellNotWritable", "GuardedDsdWrites", "STATE_EDIT", "cell_writable", "dsd_write"]

STATE_EDIT = "dsd.semester_state.edit"


class CellNotWritable(ValidationError):
    """The cell is closed, or not opened and the user cannot change states (D86).

    A ``ValidationError`` subclass, so screens show it as usual, but a bulk operation can
    catch exactly this one to skip the cell without hiding other validation errors.
    """


def cell_writable(
    user,
    code: str,
    dsd_semester: DsdSemester,
    coordination_id: int,
    *,
    permission_registry: PermissionRegistry = registry,
) -> bool:
    """Tell whether ``dsd_write`` would let the user write the cell, without writing (D86).

    Used to show or hide buttons; the write itself is always checked again by ``dsd_write``.

    Args:
        user: the user.
        code: the scoped action that covers the write.
        dsd_semester: the semester of the data.
        coordination_id: the coordination that owns the data.
        permission_registry: where ``code`` is registered.

    Returns:
        True if the user covers the coordination and the cell is open, or not opened and the
        user may change states; False if it is closed or the user does not cover it.
    """
    if not permission_registry.can_on_coordination(user, code, coordination_id):
        return False
    status = (
        CoordinationSemester.objects.filter(
            dsd_semester=dsd_semester, coordination_id=coordination_id
        )
        .values_list("status", flat=True)
        .first()
    )
    if status == CLOSED:
        return False
    return status is not None or registry.can(user, STATE_EDIT)


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
            raise CellNotWritable(
                _(
                    "O semestre %(number)s de %(year)s está fechado para esta coordenação: "
                    "só leitura."
                )
                % {"number": dsd_semester.number, "year": year}
            )
        if status is None and not registry.can(user, STATE_EDIT):
            raise CellNotWritable(
                _("O semestre %(number)s de %(year)s ainda não foi aberto para esta coordenação.")
                % {"number": dsd_semester.number, "year": year}
            )
        token = _ACTIVE.set((dsd_semester.pk, coordination_id))
        try:
            yield
        finally:
            _ACTIVE.reset(token)
