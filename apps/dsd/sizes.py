"""Pure size rule of the groups of a turma (no Django).

Implements: docs/backlog_fase2.md T3.3; D90 (the size of a group is not stored: it is the size of
the turma shared by its groups, Q6). The size of what a merge puts together is the sum of the
sizes of its members, and that sum is what the rooms of the campus are checked against.
"""

from __future__ import annotations


def group_students(turma_students: int, groups: int) -> int:
    """Return the number of students of each group of a turma divided into ``groups``.

    The groups of a turma share its size equally and the division rounds up, so that a room that
    holds the result holds any group (D90). One group is the whole turma.

    Args:
        turma_students: the students of the turma (the real number if it exists, else the
            estimate, D81).
        groups: the number of groups the turma is divided into, at least 1.

    Returns:
        ``ceil(turma_students / groups)``.

    Raises:
        ValueError: if ``groups`` is below 1.
    """
    if groups < 1:
        raise ValueError("A turma has at least one group.")
    return -(-turma_students // groups)
