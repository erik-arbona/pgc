"""Unit tests for the teacher hours range rule (no database needed).

Implements: docs/especificacao/05_dsd_regras.md – annual range of lesson hours; D11 (lowest
maximum wins), D12 (weekly hours summed over both semesters), D46 (range per teacher type),
D56, D58. The rule has validity dates: the range in force on a date is the one with the latest
``valid_from`` on or before it.
"""

import itertools
import random
from datetime import date
from decimal import Decimal

import pytest

from apps.staff.load_ranges import (
    COMPETITION,
    FULL_TIME,
    HABITUAL_COLLABORATOR,
    RangeRule,
    RuleKind,
    TeacherFacts,
    resolve_load_range,
)

D_OLD = date(2026, 9, 1)
D_NEW = date(2027, 9, 1)
D_FAR = date(2030, 1, 1)

CATEGORY, POSITION, TYPE = RuleKind.CATEGORY, RuleKind.POSITION, RuleKind.TEACHER_TYPE


def rule(id, kind, ref, maximum, minimum=None, valid_from=D_OLD):
    """Build a rule; the minimum defaults to None (no minimum)."""
    return RangeRule(
        id=id,
        kind=kind,
        ref=ref,
        minimum=None if minimum is None else Decimal(minimum),
        maximum=Decimal(maximum),
        valid_from=valid_from,
    )


def full_time(category=1, positions=()):
    """Facts of a full-time teacher."""
    return TeacherFacts(FULL_TIME, category, frozenset(positions))


# --- named edge cases ----------------------------------------------------------------------


def test_a_category_rule_alone_gives_its_range():
    """A full-time teacher with only a category rule gets that range."""
    result = resolve_load_range([rule(1, CATEGORY, 1, 14, 6)], full_time(), D_NEW)
    assert (result.minimum, result.maximum, result.rule_id) == (Decimal(6), Decimal(14), 1)
    assert result.missing == frozenset()


def test_the_lowest_maximum_wins_between_category_and_position():
    """Category 14 h and a position with 10 h: the position's range applies (D11)."""
    rules = [rule(1, CATEGORY, 1, 14, 6), rule(2, POSITION, 10, 10, 4)]
    result = resolve_load_range(rules, full_time(positions=[10]), D_NEW)
    assert (result.minimum, result.maximum, result.rule_id) == (Decimal(4), Decimal(10), 2)


def test_a_position_with_a_higher_maximum_does_not_win():
    """The category's lower maximum is kept when the position allows more."""
    rules = [rule(1, CATEGORY, 1, 10, 6), rule(2, POSITION, 10, 16, 8)]
    result = resolve_load_range(rules, full_time(positions=[10]), D_NEW)
    assert result.rule_id == 1 and result.maximum == Decimal(10)


def test_with_several_positions_the_lowest_maximum_of_all_applies():
    """Category plus three positions: the minimum of the maxima wins."""
    rules = [
        rule(1, CATEGORY, 1, 14, 6),
        rule(2, POSITION, 10, 12, 5),
        rule(3, POSITION, 11, 8, 3),
        rule(4, POSITION, 12, 11, 4),
    ]
    result = resolve_load_range(rules, full_time(positions=[10, 11, 12]), D_NEW)
    assert result.rule_id == 3 and result.maximum == Decimal(8)


def test_the_minimum_is_the_one_of_the_winning_rule_not_a_mix():
    """A lower maximum comes with its own minimum, even if another rule has a lower one."""
    rules = [rule(1, CATEGORY, 1, 14, 2), rule(2, POSITION, 10, 8, 7)]
    result = resolve_load_range(rules, full_time(positions=[10]), D_NEW)
    assert (result.minimum, result.maximum) == (Decimal(7), Decimal(8))


def test_a_tie_on_the_maximum_takes_the_lowest_minimum():
    """Equal maxima: the rule with the lowest minimum wins, and the other is reported."""
    rules = [rule(1, CATEGORY, 1, 10, 6), rule(2, POSITION, 10, 10, 4)]
    result = resolve_load_range(rules, full_time(positions=[10]), D_NEW)
    assert result.rule_id == 2 and result.minimum == Decimal(4)
    assert result.tied_rule_ids == (1,)


def test_a_tie_counts_a_missing_minimum_as_the_lowest():
    """A rule with no minimum beats an equal-maximum rule that has one."""
    rules = [rule(1, CATEGORY, 1, 10, 3), rule(2, POSITION, 10, 10, None)]
    result = resolve_load_range(rules, full_time(positions=[10]), D_NEW)
    assert result.rule_id == 2 and result.minimum is None


def test_a_full_tie_is_broken_by_a_fixed_order_not_by_input_order():
    """Same maximum and minimum: position, then category, then id; the order of the list is
    irrelevant."""
    a = rule(5, CATEGORY, 1, 10, 4)
    b = rule(9, POSITION, 10, 10, 4)
    for rules in ([a, b], [b, a]):
        assert resolve_load_range(rules, full_time(positions=[10]), D_NEW).rule_id == 9


def test_the_day_a_rule_starts_it_is_in_force_and_the_day_before_it_is_not():
    """``valid_from`` is inclusive."""
    rules = [rule(1, CATEGORY, 1, 14, 6, valid_from=D_NEW)]
    assert resolve_load_range(rules, full_time(), D_NEW).rule_id == 1
    assert resolve_load_range(rules, full_time(), date(2027, 8, 31)) is None


def test_a_newer_rule_replaces_the_old_one_from_its_date():
    """Before D_NEW the old range applies; from D_NEW on, the new one."""
    rules = [
        rule(1, CATEGORY, 1, 14, 6, valid_from=D_OLD),
        rule(2, CATEGORY, 1, 12, 6, valid_from=D_NEW),
    ]
    assert resolve_load_range(rules, full_time(), date(2027, 8, 31)).maximum == Decimal(14)
    assert resolve_load_range(rules, full_time(), D_NEW).maximum == Decimal(12)


def test_a_future_rule_is_ignored_until_its_date():
    """A rule that starts in the future does not apply today."""
    rules = [rule(1, CATEGORY, 1, 14, 6), rule(2, CATEGORY, 1, 9, 3, valid_from=D_FAR)]
    assert resolve_load_range(rules, full_time(), D_NEW).rule_id == 1


def test_no_rule_in_force_returns_none():
    """Nothing defined is a gap in the data, not an error."""
    assert resolve_load_range([], full_time(), D_NEW) is None
    assert (
        resolve_load_range([rule(1, CATEGORY, 1, 14, 6, valid_from=D_FAR)], full_time(), D_NEW)
        is None
    )


def test_missing_rules_are_listed_when_others_exist():
    """A position without a rule is reported as missing; the rest still resolves."""
    result = resolve_load_range([rule(1, CATEGORY, 1, 14, 6)], full_time(positions=[10]), D_NEW)
    assert result.rule_id == 1
    assert result.missing == frozenset({(POSITION, 10)})


def test_rules_of_other_categories_and_positions_are_ignored():
    """Rules that belong to someone else do not change the result."""
    rules = [
        rule(1, CATEGORY, 1, 14, 6),
        rule(2, CATEGORY, 2, 5, 1),
        rule(3, POSITION, 99, 4, 1),
    ]
    assert resolve_load_range(rules, full_time(), D_NEW).rule_id == 1


def test_duplicate_position_ids_count_once():
    """The same position twice is the same position."""
    facts = TeacherFacts(FULL_TIME, 1, frozenset([10]))
    rules = [rule(1, CATEGORY, 1, 14, 6), rule(2, POSITION, 10, 9, 3)]
    assert resolve_load_range(rules, facts, D_NEW).rule_id == 2


@pytest.mark.parametrize("kind", [HABITUAL_COLLABORATOR, COMPETITION])
def test_a_collaborator_or_competition_teacher_uses_the_type_range_instead_of_the_category(kind):
    """The type range replaces the category range; the minimum may be absent."""
    rules = [rule(1, CATEGORY, 1, 14, 6), rule(2, TYPE, kind, 20, None)]
    result = resolve_load_range(rules, TeacherFacts(kind, 1), D_NEW)
    assert (result.rule_id, result.maximum, result.minimum) == (2, Decimal(20), None)


@pytest.mark.parametrize("kind", [HABITUAL_COLLABORATOR, COMPETITION])
def test_a_collaborator_without_a_type_rule_gets_none_even_with_a_category_rule(kind):
    """The category rule is not used for them; the data gap is reported."""
    result = resolve_load_range([rule(1, CATEGORY, 1, 14, 6)], TeacherFacts(kind, 1), D_NEW)
    assert result is None


def test_each_type_uses_only_its_own_rule():
    """A collaborator does not pick up the competition teacher's range."""
    rules = [rule(1, TYPE, COMPETITION, 8), rule(2, TYPE, HABITUAL_COLLABORATOR, 20)]
    assert resolve_load_range(rules, TeacherFacts(HABITUAL_COLLABORATOR, 1), D_NEW).rule_id == 2
    assert resolve_load_range(rules, TeacherFacts(COMPETITION, 1), D_NEW).rule_id == 1


def test_a_maximum_of_zero_is_a_valid_range():
    """Zero hours is allowed and wins as the lowest maximum."""
    rules = [rule(1, CATEGORY, 1, 14, 6), rule(2, POSITION, 10, 0, 0)]
    assert resolve_load_range(rules, full_time(positions=[10]), D_NEW).maximum == Decimal(0)


def test_decimal_hours_are_kept_exactly():
    """Half hours and other decimals are not rounded."""
    result = resolve_load_range([rule(1, CATEGORY, 1, "13.50", "6.25")], full_time(), D_NEW)
    assert (result.minimum, result.maximum) == (Decimal("6.25"), Decimal("13.50"))


def test_positions_on_a_teacher_who_is_not_full_time_are_an_error():
    """Only full-time teachers hold positions (D56): anything else is broken input."""
    with pytest.raises(ValueError):
        resolve_load_range([], TeacherFacts(HABITUAL_COLLABORATOR, 1, frozenset([10])), D_NEW)


def test_a_rule_with_the_minimum_above_the_maximum_is_an_error():
    """Inconsistent data is refused instead of being resolved."""
    with pytest.raises(ValueError):
        resolve_load_range([rule(1, CATEGORY, 1, 5, 9)], full_time(), D_NEW)


def test_two_rules_for_the_same_subject_and_date_are_an_error():
    """The data layer must prevent overlaps; the function refuses ambiguity."""
    rules = [rule(1, CATEGORY, 1, 14, 6), rule(2, CATEGORY, 1, 12, 6)]
    with pytest.raises(ValueError):
        resolve_load_range(rules, full_time(), D_NEW)


# --- exhaustive check against a brute-force oracle -----------------------------------------

MAXIMA = (6, 8, 12)  # few values on purpose, so that ties are frequent
AS_OF_DATES = (date(2027, 8, 31), D_NEW, D_FAR)


def in_force(rules, kind, ref, as_of):
    """Oracle: the rule of a subject in force on a date, found by sorting."""
    own = sorted(
        (r for r in rules if r.kind == kind and r.ref == ref and r.valid_from <= as_of),
        key=lambda r: r.valid_from,
    )
    return own[-1] if own else None


def expected_subjects(facts):
    """Oracle: which (kind, ref) subjects a teacher's range depends on."""
    if facts.teacher_type == FULL_TIME:
        return [(CATEGORY, facts.category_id)] + [(POSITION, p) for p in sorted(facts.position_ids)]
    return [(TYPE, facts.teacher_type)]


def option_sets(subject, next_id):
    """Rule options for one subject: none, one rule, or an old rule replaced by a new one."""
    kind, ref = subject
    yield []
    for m in MAXIMA:
        yield [
            RangeRule(next_id, kind, ref, None if kind == TYPE else Decimal(1), Decimal(m), D_OLD)
        ]
    for old, new in itertools.product(MAXIMA, MAXIMA):
        yield [
            RangeRule(
                next_id, kind, ref, None if kind == TYPE else Decimal(1), Decimal(old), D_OLD
            ),
            RangeRule(
                next_id + 1, kind, ref, None if kind == TYPE else Decimal(1), Decimal(new), D_NEW
            ),
        ]


def all_facts():
    """Every teacher configuration: 2 categories x 8 position subsets, plus the 2 other types."""
    positions = (10, 11, 12)
    for category in (1, 2):
        for size in range(len(positions) + 1):
            for chosen in itertools.combinations(positions, size):
                yield full_time(category, chosen)
    yield TeacherFacts(HABITUAL_COLLABORATOR, 1)
    yield TeacherFacts(COMPETITION, 1)


def test_exhaustive_agreement_with_the_brute_force_oracle():
    """For every teacher, rule set and date, the function agrees with a simple oracle."""
    checked = 0
    for facts in all_facts():
        subjects = expected_subjects(facts)
        decoys = [
            RangeRule(
                900, CATEGORY, 2 if facts.category_id == 1 else 1, Decimal(1), Decimal(1), D_OLD
            )
        ]
        for combo in itertools.product(
            *(list(option_sets(s, 100 + 10 * i)) for i, s in enumerate(subjects))
        ):
            rules = [r for part in combo for r in part] + decoys
            for as_of in AS_OF_DATES:
                result = resolve_load_range(rules, facts, as_of)
                found = [in_force(rules, k, ref, as_of) for k, ref in subjects]
                present = [r for r in found if r is not None]
                if not present:
                    assert result is None
                else:
                    assert result.maximum == min(r.maximum for r in present)
                    winner = next(r for r in present if r.id == result.rule_id)
                    assert winner.maximum == result.maximum
                    assert result.minimum == winner.minimum
                    assert result.missing == frozenset(
                        s for s, r in zip(subjects, found, strict=True) if r is None
                    )
                    if result.minimum is not None:
                        assert result.minimum <= result.maximum
                    if facts.teacher_type != FULL_TIME:
                        assert winner.kind == TYPE
                checked += 1
    assert checked > 5000


def test_the_result_does_not_depend_on_the_order_of_the_rules():
    """Shuffling the rules never changes the answer."""
    rng = random.Random(2027)
    rules = [
        rule(1, CATEGORY, 1, 10, 4),
        rule(2, POSITION, 10, 10, 4),
        rule(3, POSITION, 11, 10, 2),
        rule(4, POSITION, 11, 7, 2, valid_from=D_NEW),
        rule(5, CATEGORY, 1, 9, 4, valid_from=D_NEW),
    ]
    facts = full_time(positions=[10, 11])
    for as_of in AS_OF_DATES:
        baseline = resolve_load_range(rules, facts, as_of)
        for _ in range(50):
            shuffled = rules[:]
            rng.shuffle(shuffled)
            assert resolve_load_range(shuffled, facts, as_of) == baseline


def test_adding_a_position_never_raises_the_maximum():
    """More positions can only keep or lower the maximum."""
    rules = [rule(1, CATEGORY, 1, 12, 5)] + [
        rule(10 + p, POSITION, p, m, 3) for p, m in ((10, 14), (11, 9), (12, 11))
    ]
    previous = resolve_load_range(rules, full_time(), D_NEW).maximum
    for positions in ([10], [10, 11], [10, 11, 12]):
        current = resolve_load_range(rules, full_time(positions=positions), D_NEW).maximum
        assert current <= previous
        previous = current
