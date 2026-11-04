"""Pure rules for the overview of a coordination (T6.1).

Implements: docs/especificacao/07_arquitetura.md – overview of the coordination; D20, D98.

No dependency on views or models. ``attention_items`` decides what needs attention from facts
already computed (units still to assign, obsolete units, the state of each teacher's load, reason
and extra hours); ``load_bar`` turns an annual load and its range into the proportions a bar
needs. Tenders and deadlines are not here: they do not exist yet (D98).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from .below_minimum import MinimumReasonState
from .extra_hours import ExtraStatus
from .load_status import LoadStatus

ZERO = Decimal("0.0")
HUNDRED = Decimal("100")
ONE_DECIMAL = Decimal("0.1")


class AttentionKind(StrEnum):
    """What can need the attention of the coordinator, in order of urgency."""

    UNASSIGNED_UNITS = "unassigned_units"  # lessons that still have no teacher
    STALE_UNITS = "stale_units"  # units the plan and the turmas no longer call for
    REASON_MISSING = "reason_missing"  # below the minimum and no reason given
    REASON_REFUSED = "reason_refused"  # the Executive Board refused the reason
    REASON_PENDING = "reason_pending"  # waiting for the Executive Board
    EXTRA_PENDING = "extra_pending"  # extra hours the teacher has not accepted
    NO_RANGE = "no_range"  # no hours range in force for the teacher


# The order in which the items are listed (the declaration order above).
_ORDER = list(AttentionKind)


@dataclass(frozen=True)
class TeacherFacts:
    """What the overview needs to know about one teacher.

    Attributes:
        teacher_id: the teacher.
        status: the state of the annual load against the range (D72-D74).
        minimum_reason: where the reason for a load below the minimum stands (D16, D97).
        extra: whether the extra hours are covered by the teacher's acceptance (D13, D96).
    """

    teacher_id: int
    status: LoadStatus
    minimum_reason: MinimumReasonState
    extra: ExtraStatus


@dataclass(frozen=True)
class AttentionItem:
    """One thing that needs attention.

    Attributes:
        kind: what it is.
        count: how many units or teachers it concerns.
        teacher_ids: the teachers it concerns, in id order (empty for units).
    """

    kind: AttentionKind
    count: int
    teacher_ids: tuple[int, ...] = ()


def attention_items(
    unassigned_units: int, stale_units: int, teachers: Iterable[TeacherFacts]
) -> list[AttentionItem]:
    """List what needs attention in a coordination, most urgent first (D20, D98).

    Args:
        unassigned_units: the units of the semester that are current and have no teacher.
        stale_units: the obsolete units of the semester.
        teachers: the facts of each teacher of the coordination.

    Returns:
        One item per kind that applies, in a fixed order; empty when nothing is pending. A reason
        that the board accepted, extra hours that were accepted and loads within the range need
        no attention.
    """
    people: dict[AttentionKind, list[int]] = {}
    for teacher in teachers:
        if teacher.status == LoadStatus.NO_RANGE:
            people.setdefault(AttentionKind.NO_RANGE, []).append(teacher.teacher_id)
        if teacher.minimum_reason == MinimumReasonState.MISSING:
            people.setdefault(AttentionKind.REASON_MISSING, []).append(teacher.teacher_id)
        elif teacher.minimum_reason == MinimumReasonState.REFUSED:
            people.setdefault(AttentionKind.REASON_REFUSED, []).append(teacher.teacher_id)
        elif teacher.minimum_reason == MinimumReasonState.PENDING:
            people.setdefault(AttentionKind.REASON_PENDING, []).append(teacher.teacher_id)
        if teacher.extra == ExtraStatus.PENDING:
            people.setdefault(AttentionKind.EXTRA_PENDING, []).append(teacher.teacher_id)
    items = []
    if unassigned_units > 0:
        items.append(AttentionItem(AttentionKind.UNASSIGNED_UNITS, unassigned_units))
    if stale_units > 0:
        items.append(AttentionItem(AttentionKind.STALE_UNITS, stale_units))
    for kind, ids in people.items():
        ordered = tuple(sorted(ids))
        items.append(AttentionItem(kind, len(ordered), ordered))
    return sorted(items, key=lambda item: _ORDER.index(item.kind))


@dataclass(frozen=True)
class LoadBar:
    """The proportions of the bar of a teacher's annual load, in percent of the bar.

    Attributes:
        scale: the hours the full bar stands for (the larger of the maximum and the hours).
        fill_percent: how much of the bar the hours fill.
        minimum_percent: where the minimum marker sits, or ``None`` if the range has no minimum
            or there is no range.
        maximum_percent: where the maximum marker sits, or ``None`` if there is no range.
    """

    scale: Decimal
    fill_percent: Decimal
    minimum_percent: Decimal | None
    maximum_percent: Decimal | None


def _percent(value: Decimal, scale: Decimal) -> Decimal:
    """Return ``value`` as a percentage of ``scale`` with one decimal, half up."""
    return (value / scale * HUNDRED).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP)


def load_bar(hours: Decimal, minimum: Decimal | None, maximum: Decimal | None) -> LoadBar:
    """Return the proportions of the bar for an annual load and its range (D20, D98).

    The bar is scaled to the larger of the maximum and the hours, so that an excess still fits
    and the maximum marker moves back; the minimum and maximum are markers on it.

    Args:
        hours: the annual teaching hours.
        minimum: the minimum of the range, or ``None``.
        maximum: the maximum of the range, or ``None`` when no range is in force.

    Returns:
        The fill and the markers, each from 0 to 100.
    """
    scale = max(hours, maximum) if maximum is not None else hours
    if scale <= 0:
        return LoadBar(max(scale, ZERO), ZERO, None, None)
    return LoadBar(
        scale=scale,
        fill_percent=_percent(hours, scale),
        minimum_percent=None if minimum is None else _percent(minimum, scale),
        maximum_percent=None if maximum is None else _percent(maximum, scale),
    )
