"""Adapters between the academic models and the pure domain rules.

Implements: D47 – keeps ``cross_course`` free of Django.
"""

from __future__ import annotations

from decimal import Decimal

from .cross_course import SubjectFacts
from .models import Subject


def facts_for(subject: Subject) -> SubjectFacts:
    """Build the domain facts of a subject.

    Args:
        subject: a saved subject.

    Returns:
        The subject's facts, with weekly hours keyed by class type code.
    """
    weekly: dict[str, Decimal] = {
        load.class_type.code: Decimal(load.weekly_hours)
        for load in subject.class_loads.select_related("class_type")
    }
    return SubjectFacts(
        id=subject.pk,
        course_id=subject.study_plan.course_id,
        plan_id=subject.study_plan_id,
        name=subject.name,
        ects=subject.ects,
        semester=subject.semester,
        semester_hours=subject.semester_hours,
        weekly_hours=weekly,
    )
