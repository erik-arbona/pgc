"""Domain rule: how many students a turma has, from the forecast and the real enrollment.

Implements: D76 – the DSD is made before the enrollment, with a forecast number; when the real
number arrives it replaces the forecast and the DSD is updated; D81. Pure Python: no Django.
"""

from __future__ import annotations

from dataclasses import dataclass

FORECAST = "forecast"
ACTUAL = "actual"


@dataclass(frozen=True)
class EffectiveStudents:
    """The number of students that counts for a turma.

    Attributes:
        students: the number.
        kind: ``"actual"`` or ``"forecast"``: which of the two it comes from.
        provisional: True while it is only a forecast.
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


def effective_students(forecast: int | None, actual: int | None) -> EffectiveStudents | None:
    """Return the number of students that counts: the real one if it exists, else the forecast.

    Args:
        forecast: the forecast number, or ``None`` if there is none.
        actual: the real number, or ``None`` if it has not arrived.

    Returns:
        The number with its kind, provisional while only the forecast exists; ``None`` when
        neither has been entered. Zero is a number like any other.

    Raises:
        TypeError: if a value is not a whole number.
        ValueError: if a value is negative.
    """
    _check(forecast, "forecast")
    _check(actual, "actual")
    if actual is not None:
        return EffectiveStudents(actual, ACTUAL, provisional=False)
    if forecast is not None:
        return EffectiveStudents(forecast, FORECAST, provisional=True)
    return None


def size_change(forecast: int | None, actual: int | None) -> int | None:
    """Return how much the real number differs from the forecast.

    Args:
        forecast: the forecast number.
        actual: the real number.

    Returns:
        ``actual - forecast`` when both exist (negative if fewer students came), otherwise
        ``None``: with no real number nothing has changed yet, and with no forecast there is
        nothing to compare. The alerts of T4.5 use it to flag turmas whose size changed.

    Raises:
        TypeError: if a value is not a whole number.
        ValueError: if a value is negative.
    """
    _check(forecast, "forecast")
    _check(actual, "actual")
    if forecast is None or actual is None:
        return None
    return actual - forecast
