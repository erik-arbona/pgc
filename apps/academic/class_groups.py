"""Domain rule: the curricular year of a turma (class group) in an academic year.

Implements: D49 – a turma is a cohort that enters in an intake year and moves up one
curricular year each academic year, until its optional last academic year.
Pure Python: no Django.
"""

from __future__ import annotations


def curricular_year_in(
    intake_year: int, academic_year: int, last_year: int | None = None
) -> int | None:
    """Return the curricular year of a turma in an academic year.

    Args:
        intake_year: start year of the academic year in which the turma enters (1st year).
        academic_year: start year of the academic year being asked about.
        last_year: start year of the last academic year of the turma, or ``None`` if it is
            still active (for example when all its students left, D49).

    Returns:
        The curricular year (1 in the intake year, 2 the next, ...), or ``None`` before
        the turma enters or after its last academic year.
    """
    if academic_year < intake_year:
        return None
    if last_year is not None and academic_year > last_year:
        return None
    return academic_year - intake_year + 1
