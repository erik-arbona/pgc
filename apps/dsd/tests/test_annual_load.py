"""Tests for the annual teaching hours of a teacher and the range that applies (T4.3).

Implements: docs/especificacao/05_dsd_regras.md – the range is measured in weekly lesson hours
summed over the two semesters and validates only the lesson hours; a range change applies from
its date; D12, D58, D72.

The expected numbers are written out by hand, never taken from the module.
"""

import itertools
from datetime import date
from decimal import Decimal

import pytest

from apps.dsd.annual_load import AnnualTeachingHours, annual_load, annual_teaching_hours
from apps.dsd.teaching_hours import (
    AssignmentFact,
    TeachingUnitFact,
    semester_teaching_hours,
)
from apps.staff.load_ranges import (
    FULL_TIME,
    HABITUAL_COLLABORATOR,
    RangeRule,
    RuleKind,
    TeacherFacts,
)

D = Decimal
WEEKS = D("15")
TODAY = date(2026, 11, 2)


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


def semester(*units):
    """Teaching hours of a semester."""
    return semester_teaching_hours(list(units), WEEKS)


def rule(rid, kind, ref, maximum, minimum=None, valid_from=date(2026, 1, 1)):
    """Build a range rule."""
    return RangeRule(
        id=rid,
        kind=kind,
        ref=ref,
        minimum=None if minimum is None else D(str(minimum)),
        maximum=D(str(maximum)),
        valid_from=valid_from,
    )


DOCTOR = TeacherFacts(teacher_type=FULL_TIME, category_id=1)


def test_the_annual_total_is_the_sum_of_the_two_semesters_with_the_detail_of_each():
    """12 weekly hours in the first semester and 9.5 in the second make 21.5 in the year."""
    first = semester(unit(1, "T", 8, [(1, 100)]), unit(2, "P", 4, [(1, 100)]))
    second = semester(unit(3, "T", 9.5, [(1, 100)]))
    (teacher,) = annual_teaching_hours(first, second)
    assert teacher.teacher_id == 1
    assert teacher.semester_weekly_hours == (D("12"), D("9.5"))
    assert teacher.weekly_hours == D("21.5")


def test_a_teacher_with_hours_in_only_one_semester_has_zero_in_the_other():
    """Teachers are the union of both semesters; the missing one counts as zero."""
    first = semester(unit(1, "T", 6, [(1, 100)]))
    second = semester(unit(2, "T", 4, [(2, 100)]))
    by_id = {t.teacher_id: t for t in annual_teaching_hours(first, second)}
    assert by_id[1].semester_weekly_hours == (D("6"), D("0"))
    assert by_id[2].semester_weekly_hours == (D("0"), D("4"))
    assert (by_id[1].weekly_hours, by_id[2].weekly_hours) == (D("6"), D("4"))


def test_shared_classes_and_groups_come_through_to_the_annual_total():
    """The annual total uses the semester figures, so shares and groups already count."""
    first = semester(
        unit(1, "P", 2, [(1, 100)], subgroup=1), unit(2, "P", 2, [(1, 100)], subgroup=2)
    )
    second = semester(unit(3, "T", 3, [(1, 60), (2, 40)]))
    by_id = {t.teacher_id: t for t in annual_teaching_hours(first, second)}
    assert by_id[1].weekly_hours == D("5.8")  # 4 + 1.8
    assert by_id[2].weekly_hours == D("1.2")


def test_nobody_in_either_semester_gives_no_teachers():
    """Two empty semesters have nobody to total."""
    assert annual_teaching_hours(semester(), semester()) == ()


def test_the_result_does_not_depend_on_the_order_of_the_inputs():
    """Swapping the semesters swaps the detail and leaves the total as it was."""
    first = semester(unit(1, "T", 6, [(1, 100)]))
    second = semester(unit(2, "T", 4, [(1, 100)]))
    (a,) = annual_teaching_hours(first, second)
    (b,) = annual_teaching_hours(second, first)
    assert a.weekly_hours == b.weekly_hours == D("10")
    assert a.semester_weekly_hours == tuple(reversed(b.semester_weekly_hours))


def test_the_load_joins_the_total_with_the_range_in_force_on_the_date():
    """The range comes from the real resolver for the given date."""
    first = semester(unit(1, "T", 8, [(1, 100)]))
    second = semester(unit(2, "T", 6, [(1, 100)]))
    rules = [rule(1, RuleKind.CATEGORY, 1, 16, minimum=8)]
    (teacher,) = annual_teaching_hours(first, second)
    load = annual_load(teacher, rules, DOCTOR, TODAY)
    assert load.weekly_hours == D("14")
    assert (load.range.minimum, load.range.maximum) == (D("8"), D("16"))
    assert load.as_of == TODAY


def test_a_range_change_applies_from_its_date_and_not_before():
    """A rule that starts in the new year changes the range only from that day (D58)."""
    first = semester(unit(1, "T", 8, [(1, 100)]))
    (teacher,) = annual_teaching_hours(first, semester())
    rules = [
        rule(1, RuleKind.CATEGORY, 1, 16, valid_from=date(2026, 1, 1)),
        rule(2, RuleKind.CATEGORY, 1, 12, valid_from=date(2027, 1, 1)),
    ]
    assert annual_load(teacher, rules, DOCTOR, date(2026, 12, 31)).range.maximum == D("16")
    assert annual_load(teacher, rules, DOCTOR, date(2027, 1, 1)).range.maximum == D("12")


def test_the_lowest_maximum_wins_when_the_teacher_has_a_category_and_a_position():
    """Category 16 h and position 10 h: the position's range applies (D11, D58)."""
    (teacher,) = annual_teaching_hours(semester(unit(1, "T", 5, [(1, 100)])), semester())
    rules = [
        rule(1, RuleKind.CATEGORY, 1, 16, minimum=8),
        rule(2, RuleKind.POSITION, 7, 10, minimum=4),
    ]
    facts = TeacherFacts(teacher_type=FULL_TIME, category_id=1, position_ids=frozenset({7}))
    load = annual_load(teacher, rules, facts, TODAY)
    assert (load.range.minimum, load.range.maximum, load.range.rule_id) == (D("4"), D("10"), 2)


def test_a_collaborator_uses_the_range_of_their_type():
    """Habitual collaborators have their own range, not the category one (D46)."""
    (teacher,) = annual_teaching_hours(semester(unit(1, "T", 5, [(1, 100)])), semester())
    rules = [
        rule(1, RuleKind.CATEGORY, 1, 16),
        rule(2, RuleKind.TEACHER_TYPE, HABITUAL_COLLABORATOR, 6),
    ]
    facts = TeacherFacts(teacher_type=HABITUAL_COLLABORATOR, category_id=1)
    assert annual_load(teacher, rules, facts, TODAY).range.maximum == D("6")


def test_no_rule_in_force_leaves_the_range_empty_not_an_error():
    """A gap in the data gives ``None`` so that T4.4 can say 'no range'."""
    (teacher,) = annual_teaching_hours(semester(unit(1, "T", 5, [(1, 100)])), semester())
    load = annual_load(
        teacher, [rule(1, RuleKind.CATEGORY, 1, 16, valid_from=date(2030, 1, 1))], DOCTOR, TODAY
    )
    assert load.range is None
    assert load.weekly_hours == D("5")


def test_a_teacher_with_no_hours_can_still_be_given_a_range():
    """A teacher absent from both semesters has zero hours, which the minimum then flags."""
    assert annual_teaching_hours(semester(), semester()) == ()
    nothing = AnnualTeachingHours.zero(9)
    load = annual_load(nothing, [rule(1, RuleKind.CATEGORY, 1, 16, minimum=8)], DOCTOR, TODAY)
    assert (load.teacher_id, load.weekly_hours, load.semester_weekly_hours) == (
        9,
        D("0"),
        (D("0"), D("0")),
    )
    assert load.range.minimum == D("8")


def test_inconsistent_range_data_is_still_refused():
    """The resolver's errors come through: two rules starting the same day."""
    (teacher,) = annual_teaching_hours(semester(unit(1, "T", 5, [(1, 100)])), semester())
    rules = [rule(1, RuleKind.CATEGORY, 1, 16), rule(2, RuleKind.CATEGORY, 1, 14)]
    with pytest.raises(ValueError):
        annual_load(teacher, rules, DOCTOR, TODAY)


def test_preparation_and_non_teaching_hours_never_enter_the_annual_total():
    """The annual total is built from teaching hours only (D12): other classes add nothing."""
    first = semester(unit(1, "O", 3, [(1, 100)]))  # "Outra" still counts as a lesson (D70)
    (teacher,) = annual_teaching_hours(first, semester())
    assert teacher.weekly_hours == D("3")  # 3, never 3 plus preparation


HOURS_1 = ["0", "0.5", "6", "7.5"]
HOURS_2 = ["0", "1", "6.25", "9"]


def test_exhaustive_pairs_of_semesters_add_up_exactly():
    """Every pair of semester totals gives exactly their sum, with each detail kept."""
    checked = 0
    for h1, h2 in itertools.product(HOURS_1, HOURS_2):
        units1 = [unit(1, "T", h1, [(1, 100)])] if D(h1) > 0 else []
        units2 = [unit(2, "T", h2, [(1, 100)])] if D(h2) > 0 else []
        teachers = annual_teaching_hours(semester(*units1), semester(*units2))
        if D(h1) == 0 and D(h2) == 0:
            assert teachers == ()
        else:
            (teacher,) = teachers
            assert teacher.semester_weekly_hours == (D(h1), D(h2))
            assert teacher.weekly_hours == D(h1) + D(h2)
        checked += 1
    assert checked == len(HOURS_1) * len(HOURS_2)


def test_the_annual_total_adds_the_two_rounded_semester_totals():
    """Each semester shows 0.005 as 0.01, and the year is what the two shown totals add up to:
    0.02, not the rounded exact sum 0.01 (D73)."""
    first = semester(unit(1, "T", 0.5, [(1, 1), (2, 99)]))
    second = semester(unit(2, "T", 0.5, [(1, 1), (2, 99)]))
    by_id = {t.teacher_id: t for t in annual_teaching_hours(first, second)}
    assert by_id[1].semester_weekly_hours == (D("0.01"), D("0.01"))
    assert by_id[1].weekly_hours == D("0.02")
