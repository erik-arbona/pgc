"""Tests for the rule that picks the number of students of a turma (T1.1).

Implements: D76 (the DSD is made with the forecast enrolment and updated when the real one
arrives), D81. The expected values are written out by hand.
"""

import pytest

from apps.academic.enrollment import EffectiveStudents, effective_students, size_change


@pytest.mark.parametrize(
    ("forecast", "actual", "expected"),
    [
        (None, None, None),  # nothing entered yet
        (30, None, EffectiveStudents(30, "forecast", provisional=True)),
        (None, 28, EffectiveStudents(28, "actual", provisional=False)),
        (30, 28, EffectiveStudents(28, "actual", provisional=False)),  # the real one replaces
        (30, 30, EffectiveStudents(30, "actual", provisional=False)),
        (30, 0, EffectiveStudents(0, "actual", provisional=False)),  # zero is a real number
        (0, None, EffectiveStudents(0, "forecast", provisional=True)),
        (0, 12, EffectiveStudents(12, "actual", provisional=False)),
    ],
)
def test_the_real_enrolment_replaces_the_forecast_when_it_exists(forecast, actual, expected):
    """With the real number the forecast stops counting; with only a forecast the number is
    used and marked provisional (D76)."""
    assert effective_students(forecast, actual) == expected


@pytest.mark.parametrize(
    ("forecast", "actual", "expected"),
    [
        (30, 28, -2),
        (30, 35, 5),
        (30, 30, 0),
        (0, 4, 4),
        (30, None, None),  # no real number yet: nothing changed
        (None, 28, None),  # no forecast to compare with
        (None, None, None),
    ],
)
def test_size_change_is_real_minus_forecast_only_when_both_exist(forecast, actual, expected):
    """The alert about turmas whose size changed needs both numbers."""
    assert size_change(forecast, actual) == expected


@pytest.mark.parametrize("bad", [-1, -30])
def test_negative_numbers_are_refused(bad):
    """A number of students cannot be negative, in either kind."""
    with pytest.raises(ValueError):
        effective_students(bad, None)
    with pytest.raises(ValueError):
        effective_students(None, bad)
    with pytest.raises(ValueError):
        size_change(bad, 3)


def test_floats_and_bools_are_refused():
    """Students are whole numbers."""
    with pytest.raises(TypeError):
        effective_students(30.5, None)
    with pytest.raises(TypeError):
        effective_students(None, True)
