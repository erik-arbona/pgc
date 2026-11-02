"""Tests for the weekly preparation hours of a teacher (T4.2).

Implements: docs/especificacao/05_dsd_regras.md – preparation = theoretical weekly hours +
(theoretical-practical, practical and laboratory weekly hours) x 1.5, as a parameter; D14, D61,
D71 (preparation follows each lesson hour: repeated for every group and weighted by the share).

The expected numbers are written out by hand from the formula, never taken from the module.
"""

import itertools
from decimal import Decimal

import pytest

from apps.dsd.preparation import preparation_by_teacher, teacher_preparation_hours
from apps.dsd.teaching_hours import (
    AssignmentFact,
    TeachingUnitFact,
    semester_teaching_hours,
)

D = Decimal
WEEKS = D("15")
# The initial weights of the specification's formula (D61); "Outra" does not count.
WEIGHTS = {"T": D("1"), "TP": D("1.5"), "P": D("1.5"), "L": D("1.5"), "O": D("0")}


def unit(uid, class_type, hours, assignments, groups=(1,), subgroup=None):
    """Build a teaching unit; ``assignments`` is a list of (teacher id, share) pairs."""
    return TeachingUnitFact(
        id=uid,
        offering_id=1,
        class_type=class_type,
        weekly_hours=D(str(hours)),
        class_group_ids=frozenset(groups),
        subgroup_id=subgroup,
        assignments=tuple(AssignmentFact(t, D(str(s))) for t, s in assignments),
    )


def prep(units, teacher_id=1, weights=WEIGHTS):
    """Weekly preparation hours of one teacher for some units."""
    result = semester_teaching_hours(units, WEEKS)
    return teacher_preparation_hours(result.for_teacher(teacher_id), weights)


def test_the_specification_formula_is_applied_to_the_teachers_hours():
    """3 T + 2 TP + 2 P: 3 + (2 + 2) x 1.5 = 9 weekly preparation hours."""
    units = [
        unit(1, "T", 3, [(1, 100)]),
        unit(2, "TP", 2, [(1, 100)]),
        unit(3, "P", 2, [(1, 100)]),
    ]
    assert prep(units) == D("9")


def test_laboratory_hours_weigh_like_practical_hours():
    """L counts 1.5 as in the formula: 2 L = 3."""
    assert prep([unit(1, "L", 2, [(1, 100)])]) == D("3")


def test_the_other_class_type_does_not_count_by_default():
    """Its weight is 0 in the specification's formula, so it adds nothing."""
    assert prep([unit(1, "O", 4, [(1, 100)])]) == D("0")


def test_every_group_is_prepared_so_five_groups_count_five_times():
    """Five groups of a 2 h practical for one teacher: 10 lesson hours x 1.5 = 15 (D71)."""
    units = [unit(i, "P", 2, [(1, 100)], subgroup=i) for i in range(5)]
    assert prep(units) == D("15")


def test_a_merged_class_is_prepared_once():
    """Two merged turmas are one class: 2 h of T give 2, not 4."""
    assert prep([unit(1, "T", 2, [(1, 100)], groups=(10, 20))]) == D("2")


def test_preparation_follows_the_share_of_a_shared_class_type():
    """A teacher with 40% of a 3 h TP gets 1.2 lesson hours and 1.8 preparation hours."""
    units = [unit(1, "TP", 3, [(1, 60), (2, 40)])]
    assert prep(units, teacher_id=2) == D("1.8")
    assert prep(units, teacher_id=1) == D("2.7")


def test_changing_a_weight_changes_the_result_without_touching_the_hours():
    """The formula is a parameter (D61): with T weighing 2, 3 T give 6."""
    units = [unit(1, "T", 3, [(1, 100)])]
    assert prep(units) == D("3")
    assert prep(units, weights={**WEIGHTS, "T": D("2")}) == D("6")


def test_a_class_type_without_a_weight_is_an_error_not_a_silent_zero():
    """A teacher with hours of a type nobody weighed fails loudly (D61)."""
    with pytest.raises(ValueError, match="weight"):
        prep([unit(1, "X", 2, [(1, 100)])])


def test_a_teacher_without_units_has_no_preparation():
    """No assignment, no preparation hours."""
    result = semester_teaching_hours([unit(1, "T", 3, [(1, 100)])], WEEKS)
    assert teacher_preparation_hours(result.for_teacher(9), WEIGHTS) == D("0")


def test_preparation_never_changes_the_teaching_hours():
    """Preparation is separate: it does not count for the load range (D12)."""
    result = semester_teaching_hours([unit(1, "P", 2, [(1, 100)])], WEEKS)
    before = result.for_teacher(1).weekly_hours
    teacher_preparation_hours(result.for_teacher(1), WEIGHTS)
    assert result.for_teacher(1).weekly_hours == before == D("2")


def test_preparation_of_all_teachers_in_one_call():
    """The dictionary has one entry per teacher with at least one unit, each as computed alone."""
    units = [
        unit(1, "T", 3, [(1, 100)]),
        unit(2, "P", 2, [(2, 50), (3, 50)]),
    ]
    result = semester_teaching_hours(units, WEEKS)
    assert preparation_by_teacher(result, WEIGHTS) == {1: D("3"), 2: D("1.5"), 3: D("1.5")}


def test_no_units_give_no_preparation():
    """An empty semester has nobody to prepare."""
    assert preparation_by_teacher(semester_teaching_hours([], WEEKS), WEIGHTS) == {}


HOURS = ["0.5", "1", "2", "3.5"]
GROUPS = range(1, 5)
CODES = ["T", "TP", "P", "L"]


def test_exhaustive_hours_groups_and_types_match_the_formula():
    """Every class type with every hour value and number of groups gives
    groups x hours x weight, exactly."""
    checked = 0
    for code, hours, groups in itertools.product(CODES, HOURS, GROUPS):
        units = [unit(g, code, hours, [(1, 100)], subgroup=g) for g in range(groups)]
        assert prep(units) == groups * D(hours) * WEIGHTS[code]
        checked += 1
    assert checked == len(CODES) * len(HOURS) * len(GROUPS)
