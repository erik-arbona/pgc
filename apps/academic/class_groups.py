"""Domain rules of the turma (class group): its curricular year and the subjects it sees.

Implements: D49 – a turma is a cohort that enters in an intake year and moves up one
curricular year each academic year, until its optional last academic year; D75, D79 – some
courses split into tracks (percursos) from a curricular year on, each track being a turma of its
own, and a turma sees the common subjects and those of its own track.
Pure Python: no Django.
"""

from __future__ import annotations


def curricular_year_in(
    intake_year: int,
    academic_year: int,
    last_year: int | None = None,
    *,
    first_year: int = 1,
    final_year: int | None = None,
) -> int | None:
    """Return the curricular year of a turma in an academic year.

    Args:
        intake_year: start year of the academic year in which the turma enters (1st year).
        academic_year: start year of the academic year being asked about.
        last_year: start year of the last academic year of the turma, or ``None`` if it is
            still active (for example when all its students left, D49).
        first_year: first curricular year in which the turma exists. A turma of a track only
            exists from the year the track starts (D79); 1 for every other turma.
        final_year: last curricular year in which the turma exists, or ``None`` for no limit.
            The turma of a cohort whose plan has tracks stops the year before they start (D79).

    Returns:
        The curricular year (1 in the intake year, 2 the next, ...), or ``None`` before
        the turma enters, after its last academic year, or outside ``first_year`` and
        ``final_year``.
    """
    if academic_year < intake_year:
        return None
    if last_year is not None and academic_year > last_year:
        return None
    year = academic_year - intake_year + 1
    if year < first_year:
        return None
    if final_year is not None and year > final_year:
        return None
    return year


def subject_applies(subject_track_id: int | None, group_track_id: int | None) -> bool:
    """Tell whether a subject is taught to a turma, given their tracks (D79).

    Args:
        subject_track_id: the track of the subject, or ``None`` if it is common to all tracks.
        group_track_id: the track of the turma, or ``None`` for a turma without track.

    Returns:
        True for a common subject, and for a subject of the turma's own track; False for a
        subject of another track, and for a track subject when the turma has no track.
    """
    return subject_track_id is None or subject_track_id == group_track_id
