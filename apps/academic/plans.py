"""Domain rule: which study plan is in force for a curricular year in an academic year.

Implements: D48 – a new plan enters year by year, starting with the first curricular year;
the old plan keeps serving the higher years until the new plan reaches them.
Pure Python: no Django.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanFacts:
    """A study plan as the phase-out rule sees it.

    Attributes:
        id: study plan primary key.
        start_year: start year of the academic year in which the plan enters (first year).
    """

    id: int
    start_year: int


def plan_in_force(
    plans: Iterable[PlanFacts], curricular_year: int, academic_year: int
) -> int | None:
    """Return the id of the plan that serves a curricular year in an academic year.

    A plan that starts in year Y reaches curricular year k in academic year Y + k - 1, and the
    most recent plan that has reached that year wins (D48).

    Args:
        plans: all study plans of one course.
        curricular_year: year of the course, starting at 1.
        academic_year: start year of the academic year, e.g. 2027 for 2027/2028.

    Returns:
        The plan id, or ``None`` if no plan has reached that curricular year yet.
    """
    reached = [p for p in plans if p.start_year + curricular_year - 1 <= academic_year]
    if not reached:
        return None
    return max(reached, key=lambda p: p.start_year).id
