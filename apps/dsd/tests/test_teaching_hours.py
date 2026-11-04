"""Tests for the teaching hours of a teacher in a semester (T4.1).

Implements: docs/especificacao/05_dsd_regras.md – the load of a teacher adds the weekly hours of
every class type assigned, weighted by the teacher's share; a merged class counts once and each
group counts once, so N groups count N times; D12, D19, D60, D70.

The expected numbers are written out by hand from those rules, never taken from the module.
"""

import itertools
import random
from decimal import ROUND_HALF_UP, Decimal

import pytest

from apps.dsd.teaching_hours import (
    AssignmentFact,
    TeachingUnitFact,
    semester_teaching_hours,
    share_hours,
)

D = Decimal
WEEKS = D("15")
CENT = D("0.01")


def unit(uid, class_type, hours, groups=(1,), assignments=(), offering=1, subgroup=None):
    """Build a teaching unit; ``assignments`` is a list of (teacher id, share) pairs."""
    return TeachingUnitFact(
        id=uid,
        offering_id=offering,
        class_type=class_type,
        weekly_hours=D(str(hours)),
        class_group_ids=frozenset(groups),
        subgroup_id=subgroup,
        assignments=tuple(AssignmentFact(t, D(str(s))) for t, s in assignments),
    )


def weekly(result, teacher_id):
    """Weekly hours of a teacher in a result."""
    return result.for_teacher(teacher_id).weekly_hours


# --- worked examples ---------------------------------------------------------------------------


def test_each_class_type_goes_to_its_own_teacher():
    """A 3 T + 2 P subject: the teacher of T gets 3 weekly hours, the teacher of P gets 2."""
    result = semester_teaching_hours(
        [unit(1, "T", 3, assignments=[(1, 100)]), unit(2, "P", 2, assignments=[(2, 100)])], WEEKS
    )
    assert (weekly(result, 1), weekly(result, 2)) == (D("3"), D("2"))
    assert (result.for_teacher(1).semester_hours, result.for_teacher(2).semester_hours) == (
        D("45"),
        D("30"),
    )


def test_a_shared_class_type_is_split_by_the_shares():
    """3 weekly hours shared 50/50 give 1.5 each; shared 60/40 give 1.8 and 1.2."""
    half = semester_teaching_hours([unit(1, "T", 3, assignments=[(1, 50), (2, 50)])], WEEKS)
    assert (weekly(half, 1), weekly(half, 2)) == (D("1.5"), D("1.5"))
    assert half.for_teacher(1).semester_hours == D("22.5")
    sixty = semester_teaching_hours([unit(1, "T", 3, assignments=[(1, 60), (2, 40)])], WEEKS)
    assert (weekly(sixty, 1), weekly(sixty, 2)) == (D("1.8"), D("1.2"))
    assert (sixty.for_teacher(1).semester_hours, sixty.for_teacher(2).semester_hours) == (
        D("27"),
        D("18"),
    )


def test_merged_turmas_count_the_shared_class_type_once():
    """Theory of two merged turmas is one class: 2 weekly hours, not 4."""
    result = semester_teaching_hours(
        [unit(1, "T", 2, groups=(10, 20), assignments=[(1, 100)])], WEEKS
    )
    assert weekly(result, 1) == D("2")
    assert result.for_teacher(1).semester_hours == D("30")


def test_each_group_counts_once_so_five_groups_count_five_times():
    """3 groups of one course and 2 of another, 2 weekly hours each, all to one teacher: 10."""
    units = [unit(i, "P", 2, groups=(10,), subgroup=i, assignments=[(1, 100)]) for i in range(5)]
    result = semester_teaching_hours(units, WEEKS)
    assert weekly(result, 1) == D("10")
    assert result.for_teacher(1).semester_hours == D("150")


def test_groups_with_different_teachers_give_each_teacher_only_their_own():
    """Five groups, three to one teacher and two to another: 6 and 4 weekly hours."""
    units = [unit(i, "P", 2, subgroup=i, assignments=[(1 if i < 3 else 2, 100)]) for i in range(5)]
    result = semester_teaching_hours(units, WEEKS)
    assert (weekly(result, 1), weekly(result, 2)) == (D("6"), D("4"))
    assert (result.for_teacher(1).semester_hours, result.for_teacher(2).semester_hours) == (
        D("90"),
        D("60"),
    )


def test_the_same_teacher_in_two_groups_counts_twice():
    """Two groups of the same class type of the same subject add up for the same teacher."""
    units = [unit(i, "P", 2, subgroup=i, assignments=[(1, 100)], offering=7) for i in (1, 2)]
    assert weekly(semester_teaching_hours(units, WEEKS), 1) == D("4")


def test_a_teacher_with_several_subjects_adds_them_and_splits_by_class_type():
    """Merged T (2) + shared T at 60% (1.8) + TP in 2 groups (4) = 7.8, split T 3.8 and TP 4."""
    units = [
        unit(1, "T", 2, groups=(10, 20), assignments=[(1, 100)], offering=1),
        unit(2, "T", 3, assignments=[(1, 60), (2, 40)], offering=2),
        unit(3, "TP", 2, subgroup=1, assignments=[(1, 100)], offering=2),
        unit(4, "TP", 2, subgroup=2, assignments=[(1, 100)], offering=2),
    ]
    teacher = semester_teaching_hours(units, WEEKS).for_teacher(1)
    assert teacher.weekly_hours == D("7.8")
    assert teacher.semester_hours == D("117")
    assert dict(teacher.weekly_by_class_type) == {"T": D("3.8"), "TP": D("4")}


def test_lines_stay_exact_and_only_the_teacher_totals_are_rounded_to_two_decimals():
    """3 hours at 33.33 / 33.33 / 33.34: the lines are exact (0.9999, 0.9999, 1.0002) and the
    totals shown are rounded to 1.00 each (D73)."""
    result = semester_teaching_hours(
        [unit(1, "T", 3, assignments=[(1, "33.33"), (2, "33.33"), (3, "33.34")])], WEEKS
    )
    exact = [result.for_teacher(t).exact_weekly_hours for t in (1, 2, 3)]
    assert exact == [D("0.9999"), D("0.9999"), D("1.0002")]
    assert [result.for_teacher(t).lines[0].weekly_hours for t in (1, 2, 3)] == exact
    assert [weekly(result, t) for t in (1, 2, 3)] == [D("1.00"), D("1.00"), D("1.00")]
    assert sum(t.exact_weekly_hours for t in result.teachers) == D("3")


def test_totals_are_rounded_half_up_to_two_decimals():
    """0.5 h at a 1% share is 0.005: it rounds up to 0.01 (half up), not down to 0.00."""
    result = semester_teaching_hours([unit(1, "T", 0.5, assignments=[(1, 1), (2, 99)])], WEEKS)
    assert result.for_teacher(1).exact_weekly_hours == D("0.005")
    assert weekly(result, 1) == D("0.01")
    assert weekly(result, 2) == D("0.50")  # 0.495 rounds up as well


def test_each_total_is_rounded_by_itself_so_they_may_not_add_up_to_the_unit():
    """1 h in thirds: 0.3333 / 0.3333 / 0.3334 each show as 0.33; the totals add up to 0.99,
    a known effect of rounding only the totals (D73)."""
    result = semester_teaching_hours(
        [unit(1, "T", 1, assignments=[(1, "33.33"), (2, "33.33"), (3, "33.34")])], WEEKS
    )
    assert [weekly(result, t) for t in (1, 2, 3)] == [D("0.33")] * 3


def test_the_semester_total_is_the_rounded_exact_weekly_total_times_the_weeks():
    """Semester hours = round(exact weekly x weeks): 0.9999 x 15 = 14.9985 shows as 15.00."""
    result = semester_teaching_hours(
        [unit(1, "T", 3, assignments=[(1, "33.33"), (2, "66.67")])], WEEKS
    )
    assert result.for_teacher(1).semester_hours == D("15.00")


def test_semester_hours_follow_the_semester_weeks_parameter():
    """The semester hours use the weeks given (D60), not a fixed 15."""
    result = semester_teaching_hours([unit(1, "T", 3, assignments=[(1, 100)])], D("16"))
    assert result.for_teacher(1).semester_hours == D("48")
    assert result.semester_weeks == D("16")


def test_every_number_comes_with_the_line_that_explains_it():
    """Each teacher carries one line per unit with the unit hours, the share and the result."""
    result = semester_teaching_hours(
        [unit(1, "T", 3, assignments=[(1, 60), (2, 40)], offering=5)], WEEKS
    )
    (line,) = result.for_teacher(1).lines
    assert (line.unit_id, line.offering_id, line.class_type) == (1, 5, "T")
    assert (line.unit_weekly_hours, line.share, line.weekly_hours, line.semester_hours) == (
        D("3"),
        D("60"),
        D("1.8"),
        D("27"),
    )


# --- units without a teacher or with odd shares ------------------------------------------------


def test_a_unit_without_a_teacher_counts_for_nobody_and_is_reported():
    """It adds nothing to any teacher and shows a share total of zero."""
    result = semester_teaching_hours([unit(1, "T", 3)], WEEKS)
    assert result.teachers == ()
    (totals,) = result.units
    assert (totals.unit_id, totals.share_total, totals.distributed_weekly_hours) == (
        1,
        D("0"),
        D("0"),
    )


@pytest.mark.parametrize(
    ("shares", "expected_total", "expected_hours"),
    [([100], "100", "3"), ([50, 40], "90", "2.7"), ([60, 50], "110", "3.3")],
)
def test_shares_not_adding_up_to_100_are_calculated_and_reported(
    shares, expected_total, expected_hours
):
    """The calculation does not refuse them; the share total is reported for the alert."""
    assignments = list(enumerate(shares, start=1))
    result = semester_teaching_hours([unit(1, "T", 3, assignments=assignments)], WEEKS)
    (totals,) = result.units
    assert totals.share_total == D(expected_total)
    assert totals.distributed_weekly_hours == D(expected_hours)


def test_asking_for_a_teacher_with_no_units_gives_zeros():
    """A teacher without assignments has zero hours (the load range still applies later)."""
    result = semester_teaching_hours([unit(1, "T", 3, assignments=[(1, 100)])], WEEKS)
    teacher = result.for_teacher(9)
    assert (teacher.weekly_hours, teacher.semester_hours, teacher.lines) == (D("0"), D("0"), ())


def test_share_hours_is_the_unit_hours_times_the_share_over_100():
    """The single formula h x s / 100, exact."""
    assert share_hours(D("2.5"), D("40")) == D("1")
    assert share_hours(D("3"), D("33.33")) == D("0.9999")


# --- exhaustive table --------------------------------------------------------------------------

HOURS = ["0.5", "1", "2.5", "3"]
SPLITS = [[100], [50, 50], [60, 40], ["33.33", "33.33", "33.34"]]


def test_exhaustive_combinations_of_hours_groups_and_splits_match_the_formula():
    """Every combination of weekly hours, number of groups and share split gives exactly
    groups x hours x share / 100 to each teacher."""
    checked = 0
    for hours, groups, split in itertools.product(HOURS, range(1, 6), SPLITS):
        units = [
            unit(
                g,
                "P",
                hours,
                subgroup=g,
                assignments=[(t, share) for t, share in enumerate(split, start=1)],
            )
            for g in range(groups)
        ]
        result = semester_teaching_hours(units, WEEKS)
        for teacher, share in enumerate(split, start=1):
            expected = groups * D(hours) * D(str(share)) / D(100)
            assert result.for_teacher(teacher).exact_weekly_hours == expected
            assert weekly(result, teacher) == expected.quantize(CENT, ROUND_HALF_UP)
            assert result.for_teacher(teacher).semester_hours == (expected * WEEKS).quantize(
                CENT, ROUND_HALF_UP
            )
        checked += 1
    assert checked == len(HOURS) * 5 * len(SPLITS)


# --- properties on random inputs (fixed seed) --------------------------------------------------


def random_units(rng: random.Random):
    """A random semester: several offerings, merges, groups and shared assignments."""
    units = []
    for uid in range(rng.randint(1, 12)):
        teachers = rng.sample(range(1, 7), rng.randint(0, 3))
        if teachers:
            cuts = sorted(rng.sample(range(1, 100), len(teachers) - 1))
            parts = [b - a for a, b in zip([0, *cuts], [*cuts, 100], strict=True)]
        else:
            parts = []
        units.append(
            unit(
                uid,
                rng.choice(["T", "TP", "P", "L"]),
                D(rng.randint(1, 12)) / 2,
                groups=tuple(rng.sample(range(1, 6), rng.randint(1, 3))),
                subgroup=rng.choice([None, uid]),
                assignments=list(zip(teachers, parts, strict=True)),
                offering=rng.randint(1, 4),
            )
        )
    return units


@pytest.fixture(scope="module")
def cases():
    """Two hundred random semesters, always the same ones."""
    rng = random.Random(2026)
    return [random_units(rng) for _ in range(200)]


def test_hours_are_distributed_without_loss_or_duplication(cases):
    """Per unit the distributed hours are h x share total / 100; when the shares add up to
    100 they equal the unit hours; over teachers nothing is lost or duplicated."""
    for units in cases:
        result = semester_teaching_hours(units, WEEKS)
        for fact, totals in zip(sorted(units, key=lambda u: u.id), result.units, strict=True):
            share_total = sum(a.share for a in fact.assignments)
            assert totals.share_total == share_total
            assert totals.distributed_weekly_hours == fact.weekly_hours * share_total / 100
            if share_total == 100:
                assert totals.distributed_weekly_hours == fact.weekly_hours
        assert sum(t.exact_weekly_hours for t in result.teachers) == sum(
            u.distributed_weekly_hours for u in result.units
        )


def test_the_order_of_units_and_assignments_does_not_matter(cases):
    """Shuffling the input gives an identical result."""
    rng = random.Random(7)
    for units in cases:
        shuffled = []
        for fact in rng.sample(units, len(units)):
            assignments = rng.sample(fact.assignments, len(fact.assignments))
            shuffled.append(
                TeachingUnitFact(
                    id=fact.id,
                    offering_id=fact.offering_id,
                    class_type=fact.class_type,
                    weekly_hours=fact.weekly_hours,
                    class_group_ids=fact.class_group_ids,
                    subgroup_id=fact.subgroup_id,
                    assignments=tuple(assignments),
                )
            )
        assert semester_teaching_hours(shuffled, WEEKS) == semester_teaching_hours(units, WEEKS)


def test_merging_more_turmas_never_changes_any_hours(cases):
    """Adding turmas to the audience of a unit leaves every figure as it was (a merge is one
    class)."""
    for units in cases:
        wider = [
            TeachingUnitFact(
                id=u.id,
                offering_id=u.offering_id,
                class_type=u.class_type,
                weekly_hours=u.weekly_hours,
                class_group_ids=u.class_group_ids | {99, 100},
                subgroup_id=u.subgroup_id,
                assignments=u.assignments,
            )
            for u in units
        ]
        before = semester_teaching_hours(units, WEEKS)
        after = semester_teaching_hours(wider, WEEKS)
        assert [t.weekly_hours for t in before.teachers] == [t.weekly_hours for t in after.teachers]
        assert before.units == after.units


def test_n_identical_groups_multiply_the_hours_by_n(cases):
    """Replacing one unit by n copies (n groups) multiplies that teacher's hours by n."""
    for units in cases[:60]:
        base = semester_teaching_hours(units, WEEKS)
        first = units[0]
        copies = [
            TeachingUnitFact(
                id=1000 + i,
                offering_id=first.offering_id,
                class_type=first.class_type,
                weekly_hours=first.weekly_hours,
                class_group_ids=first.class_group_ids,
                subgroup_id=1000 + i,
                assignments=first.assignments,
            )
            for i in range(2)  # two extra copies: three groups in total
        ]
        tripled = semester_teaching_hours([*units, *copies], WEEKS)
        for assignment in first.assignments:
            own = share_hours(first.weekly_hours, assignment.share)
            teacher = assignment.teacher_id
            exact_before = base.for_teacher(teacher).exact_weekly_hours
            assert tripled.for_teacher(teacher).exact_weekly_hours == exact_before + 2 * own


def test_semester_hours_and_class_type_split_are_consistent(cases):
    """For every teacher: the shown totals are the exact ones rounded to two decimals, and the
    class type split and the lines add up to the exact weekly total; every line's semester
    hours are its weekly hours x weeks, exact."""
    for units in cases:
        for teacher in semester_teaching_hours(units, WEEKS).teachers:
            assert teacher.weekly_hours == teacher.exact_weekly_hours.quantize(CENT, ROUND_HALF_UP)
            assert teacher.semester_hours == (teacher.exact_weekly_hours * WEEKS).quantize(
                CENT, ROUND_HALF_UP
            )
            assert sum(h for _t, h in teacher.weekly_by_class_type) == teacher.exact_weekly_hours
            assert sum(line.weekly_hours for line in teacher.lines) == teacher.exact_weekly_hours
            for line in teacher.lines:
                assert line.semester_hours == line.weekly_hours * WEEKS


# --- invalid input -----------------------------------------------------------------------------


@pytest.mark.parametrize("hours", [0, -1, "-0.5"])
def test_non_positive_weekly_hours_are_refused(hours):
    """A class with no hours is meaningless."""
    with pytest.raises(ValueError, match="weekly_hours"):
        unit(1, "T", hours, assignments=[(1, 100)])


@pytest.mark.parametrize("share", [0, -10, "100.01", 150])
def test_a_share_outside_zero_to_100_is_refused(share):
    """A share is a percentage above 0 and at most 100."""
    with pytest.raises(ValueError, match="share"):
        AssignmentFact(1, D(str(share)))


def test_floats_and_none_are_refused_in_place_of_decimals():
    """No float arithmetic anywhere: a float or None is a type error."""
    with pytest.raises(TypeError):
        TeachingUnitFact(
            id=1, offering_id=1, class_type="T", weekly_hours=3.0, class_group_ids=frozenset({1})
        )
    with pytest.raises(TypeError):
        AssignmentFact(1, None)
    with pytest.raises(TypeError):
        share_hours(2.5, D("50"))
    with pytest.raises(TypeError):
        semester_teaching_hours([], 15.0)


@pytest.mark.parametrize("weeks", [D("0"), D("-1")])
def test_non_positive_semester_weeks_are_refused(weeks):
    """A semester has at least some weeks (D60)."""
    with pytest.raises(ValueError, match="semester_weeks"):
        semester_teaching_hours([], weeks)


def test_two_units_with_the_same_id_are_refused():
    """The unit id identifies the unit in the result."""
    with pytest.raises(ValueError, match="duplicate"):
        semester_teaching_hours(
            [unit(1, "T", 3, assignments=[(1, 100)]), unit(1, "P", 2, assignments=[(2, 100)])],
            WEEKS,
        )


def test_the_same_teacher_twice_in_one_unit_is_refused():
    """One teacher per class type of a turma or group (D19): use the share instead."""
    with pytest.raises(ValueError, match="teacher"):
        unit(1, "T", 3, assignments=[(1, 50), (1, 50)])


def test_a_unit_with_no_audience_is_refused():
    """A class is for some turma or group."""
    with pytest.raises(ValueError, match="class_group_ids"):
        unit(1, "T", 3, groups=(), assignments=[(1, 100)])


def test_no_units_give_an_empty_result():
    """An empty semester has no teachers and no units."""
    result = semester_teaching_hours([], WEEKS)
    assert (result.teachers, result.units) == ((), ())
