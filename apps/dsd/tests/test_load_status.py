"""Tests for the state of the annual load and the extra hours (T4.4).

Implements: docs/especificacao/05_dsd_regras.md – the four states of the annual load against the
range (below the minimum, in the range, at the maximum, above the maximum); extra hours = total
minus the maximum; the minimum is optional (D46); D12, D13, D58, D73, D74.

The expected states are written out by hand from the table of the specification.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.dsd.annual_load import (
    AnnualLoad,
    AnnualTeachingHours,
    annual_load,
    annual_teaching_hours,
)
from apps.dsd.load_status import LoadStatus, assess_load
from apps.dsd.teaching_hours import (
    AssignmentFact,
    TeachingUnitFact,
    semester_teaching_hours,
)
from apps.staff.load_ranges import FULL_TIME, RangeRule, ResolvedRange, RuleKind, TeacherFacts

D = Decimal
TODAY = date(2026, 11, 2)


def make_load(hours, minimum, maximum, teacher_id=1):
    """An annual load of ``hours`` against a range; ``maximum`` None means no range at all."""
    resolved = (
        None
        if maximum is None
        else ResolvedRange(
            minimum=None if minimum is None else D(str(minimum)),
            maximum=D(str(maximum)),
            rule_id=1,
            tied_rule_ids=(),
            missing=frozenset(),
        )
    )
    return AnnualLoad(
        teacher_id=teacher_id,
        semester_weekly_hours=(D(str(hours)), D("0")),
        weekly_hours=D(str(hours)),
        range=resolved,
        as_of=TODAY,
    )


# (annual hours, minimum, maximum, expected status, expected extra hours)
BELOW, IN, AT, ABOVE, NONE = (
    LoadStatus.BELOW_MINIMUM,
    LoadStatus.IN_RANGE,
    LoadStatus.AT_MAXIMUM,
    LoadStatus.ABOVE_MAXIMUM,
    LoadStatus.NO_RANGE,
)
CASES = [
    # with a minimum of 8 and a maximum of 16
    ("0", "8", "16", BELOW, "0"),
    ("7.99", "8", "16", BELOW, "0"),
    ("8", "8", "16", IN, "0"),  # reaching the minimum is already in the range
    ("8.01", "8", "16", IN, "0"),
    ("15.99", "8", "16", IN, "0"),
    ("16", "8", "16", AT, "0"),
    ("16.01", "8", "16", ABOVE, "0.01"),
    ("20", "8", "16", ABOVE, "4"),
    # without a minimum (collaborators and competition teachers, D46): never below it
    ("0", None, "16", IN, "0"),
    ("7.99", None, "16", IN, "0"),
    ("15.99", None, "16", IN, "0"),
    ("16", None, "16", AT, "0"),
    ("16.01", None, "16", ABOVE, "0.01"),
    # a minimum equal to the maximum: the maximum wins when reached
    ("15.99", "16", "16", BELOW, "0"),
    ("16", "16", "16", AT, "0"),
    ("16.01", "16", "16", ABOVE, "0.01"),
    # decimals in the range
    ("12.5", "12.5", "14.25", IN, "0"),
    ("14.25", "12.5", "14.25", AT, "0"),
    ("14.30", "12.5", "14.25", ABOVE, "0.05"),
]


@pytest.mark.parametrize(("hours", "minimum", "maximum", "status", "extra"), CASES)
def test_state_and_extra_hours_follow_the_table_of_the_specification(
    hours, minimum, maximum, status, extra
):
    """Each total against its range gives the state of the table and the extra hours."""
    assessment = assess_load(make_load(hours, minimum, maximum))
    assert assessment.status == status
    assert assessment.extra_hours == D(extra)


def test_extra_hours_exist_only_above_the_maximum():
    """In every other state there are no extra hours, whatever the total."""
    for hours, minimum, maximum, status, _extra in CASES:
        if status != ABOVE:
            assert assess_load(make_load(hours, minimum, maximum)).extra_hours == D("0")


def test_without_any_range_the_state_is_no_range_and_not_an_error():
    """A gap in the data is reported as 'no range' with no extra hours."""
    assessment = assess_load(make_load("12", None, None))
    assert (assessment.status, assessment.extra_hours, assessment.range) == (NONE, D("0"), None)


def test_the_assessment_carries_what_the_screens_need():
    """Teacher, total, semester detail, range and date travel with the state."""
    load = make_load("17", "8", "16", teacher_id=5)
    assessment = assess_load(load)
    assert assessment.teacher_id == 5
    assert assessment.weekly_hours == D("17")
    assert assessment.semester_weekly_hours == (D("17"), D("0"))
    assert assessment.range == load.range
    assert assessment.as_of == TODAY


# --- from the assignments to the state, through the whole chain --------------------------------


def one_teacher_year(first_semester_units, rules):
    """Annual load state of teacher 1 from the units of the first semester only."""
    first = semester_teaching_hours(first_semester_units, D("15"))
    second = semester_teaching_hours([], D("15"))
    hours = next(
        (t for t in annual_teaching_hours(first, second) if t.teacher_id == 1),
        None,
    )
    hours = hours or AnnualTeachingHours.zero(1)
    facts = TeacherFacts(teacher_type=FULL_TIME, category_id=1)
    return assess_load(annual_load(hours, rules, facts, TODAY))


def unit(hours, share):
    """A 48 h class given to teacher 1 with a share."""
    return TeachingUnitFact(
        id=1,
        offering_id=1,
        class_type="T",
        weekly_hours=D(str(hours)),
        class_group_ids=frozenset({1}),
        assignments=(AssignmentFact(1, D(str(share))),),
    )


RULES = [
    RangeRule(
        id=1,
        kind=RuleKind.CATEGORY,
        ref=1,
        minimum=D("8"),
        maximum=D("16"),
        valid_from=date(2026, 1, 1),
    )
]


def test_a_total_of_15_9984_exact_hours_shows_as_16_and_is_at_the_maximum():
    """48 h at a 33.33% share is 15.9984 exact; the shown total is 16.00, so the teacher is at
    the maximum, not 'in the range' (D73)."""
    assessment = one_teacher_year([unit(48, "33.33")], RULES)
    assert assessment.weekly_hours == D("16.00")
    assert assessment.status == AT
    assert assessment.extra_hours == D("0")


def test_a_total_of_15_9936_exact_hours_shows_as_15_99_and_stays_in_the_range():
    """48 h at 33.32% is 15.9936 exact, shown as 15.99: still in the range."""
    assessment = one_teacher_year([unit(48, "33.32")], RULES)
    assert (assessment.weekly_hours, assessment.status) == (D("15.99"), IN)


def test_a_teacher_with_no_units_is_below_a_minimum_but_not_without_one():
    """Zero hours is below a minimum of 8; with no minimum it is simply in the range."""
    assert one_teacher_year([], RULES).status == BELOW
    no_minimum = [
        RangeRule(
            id=1,
            kind=RuleKind.CATEGORY,
            ref=1,
            minimum=None,
            maximum=D("16"),
            valid_from=date(2026, 1, 1),
        )
    ]
    assert one_teacher_year([], no_minimum).status == IN


def test_a_total_above_the_maximum_gives_the_extra_hours_from_the_rounded_total():
    """48 h at 33.34% is 16.0032 exact, shown as 16.00 (at the maximum); 49 h at 33.34% is
    16.3366, shown as 16.34: 0.34 extra hours."""
    assert one_teacher_year([unit(48, "33.34")], RULES).status == AT
    above = one_teacher_year([unit(49, "33.34")], RULES)
    assert (above.status, above.extra_hours) == (ABOVE, D("0.34"))
