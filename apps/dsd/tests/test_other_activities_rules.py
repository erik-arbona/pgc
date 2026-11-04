"""Tests for the pure rules of the non-teaching component (T5.3).

Implements: docs/especificacao/05_dsd_regras.md – non-teaching component; D15, D95.
"""

from decimal import Decimal

import pytest

from apps.dsd.other_activities import ActivityFact, general_total, other_hours_by_teacher

D = Decimal


def test_the_hours_of_a_teacher_are_added_by_semester():
    """Two activities in semester 1 and one in semester 2."""
    facts = [
        ActivityFact(1, 1, D("2")),
        ActivityFact(1, 1, D("1.5")),
        ActivityFact(1, 2, D("4")),
    ]
    assert other_hours_by_teacher(facts) == {1: (D("3.50"), D("4.00"))}


def test_each_teacher_has_their_own_total():
    """Teachers do not mix."""
    facts = [ActivityFact(1, 1, D("2")), ActivityFact(2, 2, D("3"))]
    assert other_hours_by_teacher(facts) == {1: (D("2.00"), D("0.00")), 2: (D("0.00"), D("3.00"))}


def test_a_teacher_without_activities_is_not_listed():
    """Callers use zero as the default."""
    assert other_hours_by_teacher([]) == {}


def test_a_semester_other_than_one_or_two_is_refused():
    """Never a silent wrong semester."""
    with pytest.raises(ValueError):
        other_hours_by_teacher([ActivityFact(1, 3, D("1"))])


def test_the_general_total_adds_teaching_preparation_and_other_activities():
    """Teaching 10 + preparation 1.5 + 0.5 + other 2 + 3 = 17."""
    total = general_total(D("10"), (D("1.5"), D("0.5")), (D("2"), D("3")))
    assert total == D("17.00")


def test_the_general_total_without_other_activities_is_teaching_plus_preparation():
    """No activities, no change."""
    total = general_total(D("10"), (D("1"), D("1")), (D("0"), D("0")))
    assert total == D("12.00")
