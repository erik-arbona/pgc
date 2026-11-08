"""Data of the reports of the Executive Board of a Faculty (T6.8).

Implements: docs/especificacao/05_dsd_regras.md; D16, D69, D104.

Adapter between the models and the pure rules in ``reports``: it computes the live load of the
active teachers of the coordinations the board covers and sorts them into the three reports. The
reason for a load below the minimum goes with its teacher, because the board decides on it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from apps.staff.models import Teacher

from .load_facts import TeacherLoad, load_text, teacher_loads
from .models import BelowMinimumReason, Dsd
from .reports import ReportKind, free_hours, reports_of


@dataclass(frozen=True)
class ReportRow:
    """One teacher in a report.

    Attributes:
        teacher: the teacher.
        load: their live load (hours, state, extra hours, reason state).
        free_hours: the hours left before the maximum, or ``None`` without a range.
        reason: the reason given for a load below the minimum, with its review, if any.
        status: the state of the load in words.
    """

    teacher: Teacher
    load: TeacherLoad
    free_hours: Decimal | None
    reason: BelowMinimumReason | None
    status: str


@dataclass
class BoardReport:
    """The three reports of a Faculty in a DSD."""

    below_minimum: list[ReportRow] = field(default_factory=list)
    below_maximum: list[ReportRow] = field(default_factory=list)
    extra_hours: list[ReportRow] = field(default_factory=list)


def board_report(dsd: Dsd, coordination_ids: Iterable[int]) -> BoardReport:
    """Build the reports for the active teachers of some coordinations.

    Args:
        dsd: the DSD.
        coordination_ids: the coordinations the board covers (its Faculty's, D69).

    Returns:
        The teachers below the minimum, in range, and with extra hours, each list by name.
    """
    teachers = list(
        Teacher.objects.filter(coordination_id__in=list(coordination_ids), is_active=True)
        .select_related("coordination", "category")
        .order_by("name")
    )
    loads = teacher_loads(dsd, teachers)
    reasons = {
        reason.teacher_id: reason
        for reason in BelowMinimumReason.objects.filter(
            dsd=dsd, teacher__in=teachers
        ).select_related("review")
    }
    result = BoardReport()
    lists = {
        ReportKind.BELOW_MINIMUM: result.below_minimum,
        ReportKind.BELOW_MAXIMUM: result.below_maximum,
        ReportKind.EXTRA_HOURS: result.extra_hours,
    }
    for teacher in teachers:
        load = loads[teacher.pk]
        assessment = load.assessment
        resolved = assessment.range
        row = ReportRow(
            teacher=teacher,
            load=load,
            free_hours=free_hours(resolved.maximum if resolved else None, assessment.weekly_hours),
            reason=reasons.get(teacher.pk),
            status=load_text(load),
        )
        for kind in reports_of(assessment.status, load.extra.status):
            lists[kind].append(row)
    return result
