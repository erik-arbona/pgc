"""Domain rule: weekly preparation hours of a teacher.

Implements: docs/especificacao/05_dsd_regras.md – preparation = theoretical weekly hours +
(theoretical-practical, practical and laboratory weekly hours) x 1.5, kept as a parameter;
D14, D61, D71. Pure Python: no Django.

It applies the per-class-type weights (``academic.preparation.preparation_hours``) to the
teaching hours of the teacher that ``teaching_hours`` already computed. Preparation therefore
follows each lesson hour (D71): a class repeated for five groups is prepared five times, a
merged class once, and a shared class type only for the teacher's share. It does not count for
the annual load range, which validates the teaching hours only (D12).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from apps.academic.preparation import preparation_hours

from .teaching_hours import SemesterTeachingHours, TeacherTeachingHours, round_hours


def teacher_preparation_hours(
    teacher: TeacherTeachingHours, weights: Mapping[str, Decimal]
) -> Decimal:
    """Return the weekly preparation hours of a teacher in a semester.

    Args:
        teacher: the teacher's teaching hours, with the weekly hours of each class type.
        weights: preparation weight of each class type code (``ClassType.preparation_weight``).

    Returns:
        The sum, over the class types, of the teacher's exact weekly hours times the weight,
        rounded to two decimals (D73); zero for a teacher with no hours.

    Raises:
        ValueError: if a class type with hours has no weight (never a silent zero, D61).
    """
    return round_hours(preparation_hours(dict(teacher.weekly_by_class_type), weights))


def preparation_by_teacher(
    result: SemesterTeachingHours, weights: Mapping[str, Decimal]
) -> dict[int, Decimal]:
    """Return the weekly preparation hours of every teacher that has teaching units.

    Args:
        result: the teaching hours of the semester.
        weights: preparation weight of each class type code.

    Returns:
        A dictionary from teacher id to weekly preparation hours.

    Raises:
        ValueError: if a class type with hours has no weight.
    """
    return {t.teacher_id: teacher_preparation_hours(t, weights) for t in result.teachers}
