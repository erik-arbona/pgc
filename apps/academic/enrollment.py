"""Domain rule: how many students a turma has, from the estimate and the real enrollment.

Implements: D76 – the DSD is made before the enrollment, with an estimated number; when the real
number arrives it replaces the estimate and the DSD is updated; D81. Pure Python: no Django.
"""

from __future__ import annotations

from dataclasses import dataclass

ESTIMATED = "estimated"
ACTUAL = "actual"


@dataclass(frozen=True)
class EffectiveStudents:
    """The number of students that counts for a turma.

    Attributes:
        students: the number.
        kind: ``"actual"`` or ``"estimated"``: which of the two it comes from.
        provisional: True while it is only an estimate.
    """

    students: int
    kind: str
    provisional: bool


def _check(value: int | None, name: str) -> None:
    """Refuse anything that is not a whole, non-negative number (or ``None``).

    Raises:
        TypeError: for a float, a bool or any other type.
        ValueError: for a negative number.
    """
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be a whole number, not {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} cannot be negative, got {value}")


def effective_students(estimated: int | None, actual: int | None) -> EffectiveStudents | None:
    """Return the number of students that counts: the real one if it exists, else the estimate.

    Args:
        estimated: the estimated number, or ``None`` if there is none.
        actual: the real number, or ``None`` if it has not arrived.

    Returns:
        The number with its kind, provisional while only the estimate exists; ``None`` when
        neither has been entered. Zero is a number like any other.

    Raises:
        TypeError: if a value is not a whole number.
        ValueError: if a value is negative.
    """
    _check(estimated, "estimated")
    _check(actual, "actual")
    if actual is not None:
        return EffectiveStudents(actual, ACTUAL, provisional=False)
    if estimated is not None:
        return EffectiveStudents(estimated, ESTIMATED, provisional=True)
    return None


def size_change(estimated: int | None, actual: int | None) -> int | None:
    """Return how much the real number differs from the estimate.

    Args:
        estimated: the estimated number.
        actual: the real number.

    Returns:
        ``actual - estimated`` when both exist (negative if fewer students came), otherwise
        ``None``: with no real number nothing has changed yet, and with no estimate there is
        nothing to compare. The alerts of T4.5 use it to flag turmas whose size changed.

    Raises:
        TypeError: if a value is not a whole number.
        ValueError: if a value is negative.
    """
    _check(estimated, "estimated")
    _check(actual, "actual")
    if estimated is None or actual is None:
        return None
    return actual - estimated
