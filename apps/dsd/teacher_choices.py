"""The teachers a unit can be given to, each with the load they would have (T5.1b, T6.2).

Implements: docs/backlog_fase2.md T5.1b and T6.2; D69 (only teachers of the coordination of the
subject), D94 (one teacher per unit).

Shared by the form page of a unit and by the selector in the row of the subject page, so both
offer the same teachers with the same description.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from django.utils.translation import gettext as _

from apps.staff.models import Teacher

from .load_facts import TeacherLoad, assessment_with_unit, status_text


def candidate_teachers(coordination_id: int, current: Teacher | None = None) -> list[Teacher]:
    """Return the teachers a unit of a subject of a coordination can be given to (D69).

    Args:
        coordination_id: the coordination of the subject.
        current: the teacher the unit already has, if any. It is always listed, even if they were
            deactivated or moved to another coordination, so that a form never looks as if the
            unit had nobody.

    Returns:
        The active teachers of the coordination by name, plus ``current`` if not among them.
    """
    teachers = list(
        Teacher.objects.filter(coordination_id=coordination_id, is_active=True).order_by("name")
    )
    if current is not None and all(teacher.pk != current.pk for teacher in teachers):
        teachers.append(current)
    return teachers


def describe_candidates(
    candidates: Iterable[Teacher],
    loads: dict[int, TeacherLoad],
    coordination_id: int,
    semester_number: int,
    weekly_hours: Decimal,
    current_teacher_id: int | None,
) -> dict[int, str]:
    """Describe each candidate: the annual hours and the state they would have with the unit.

    For a teacher who does not have the unit, its hours are added to their load, in the semester
    of the unit; the current teacher already counts it, so their load is shown as it is. A teacher
    who is no longer eligible is marked.

    Args:
        candidates: the teachers to describe.
        loads: the live load of each of them (``load_facts.teacher_loads``).
        coordination_id: the coordination of the subject.
        semester_number: 1 or 2, the semester of the unit.
        weekly_hours: the weekly hours of the unit.
        current_teacher_id: the teacher the unit already has, if any.

    Returns:
        A text for each teacher id, for example ``9.00 h (no intervalo)``.
    """
    described = {}
    for teacher in candidates:
        load = loads[teacher.pk]
        assessment = (
            load.assessment
            if teacher.pk == current_teacher_id
            else assessment_with_unit(load, semester_number, weekly_hours)
        )
        text = f"{assessment.weekly_hours} h ({status_text(assessment)})"
        if not teacher.is_active:
            text += " – " + str(_("inativo"))
        elif teacher.coordination_id != coordination_id:
            text += " – " + str(_("de outra coordenação"))
        described[teacher.pk] = text
    return described
