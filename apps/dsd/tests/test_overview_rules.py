"""Tests for the pure rules of the overview of a coordination (T6.1).

Implements: docs/especificacao/07_arquitetura.md – overview of the coordination; D20, D98.
"""

from decimal import Decimal

from apps.dsd.below_minimum import MinimumReasonState
from apps.dsd.extra_hours import ExtraStatus
from apps.dsd.load_status import LoadStatus
from apps.dsd.overview import AttentionKind, TeacherFacts, attention_items, load_bar

D = Decimal


def facts(teacher_id, status=LoadStatus.IN_RANGE, reason=MinimumReasonState.NOT_NEEDED, extra=None):
    """The facts of a teacher, in range with nothing pending by default."""
    return TeacherFacts(teacher_id, status, reason, extra or ExtraStatus.NONE)


def kinds(items):
    """The kinds of the items, in order."""
    return [item.kind for item in items]


def test_nothing_pending_gives_no_items():
    """A coordination in order has nothing that needs attention."""
    assert attention_items(0, 0, [facts(1), facts(2, LoadStatus.AT_MAXIMUM)]) == []


def test_units_without_a_teacher_are_an_item_with_their_count():
    """Three lessons still to assign."""
    [item] = attention_items(3, 0, [])
    assert (item.kind, item.count) == (AttentionKind.UNASSIGNED_UNITS, 3)


def test_obsolete_units_are_an_item_with_their_count():
    """Two units the plan no longer calls for."""
    [item] = attention_items(0, 2, [])
    assert (item.kind, item.count) == (AttentionKind.STALE_UNITS, 2)


def test_a_teacher_below_the_minimum_without_a_reason_needs_one():
    """Missing reason: the coordinator has to write it."""
    [item] = attention_items(0, 0, [facts(7, LoadStatus.BELOW_MINIMUM, MinimumReasonState.MISSING)])
    assert item.kind == AttentionKind.REASON_MISSING
    assert item.teacher_ids == (7,)


def test_a_reason_waiting_for_the_board_and_a_refused_one_are_different_items():
    """Pending waits for the board; refused is back with the coordinator."""
    items = attention_items(
        0,
        0,
        [
            facts(1, LoadStatus.BELOW_MINIMUM, MinimumReasonState.PENDING),
            facts(2, LoadStatus.BELOW_MINIMUM, MinimumReasonState.REFUSED),
        ],
    )
    assert kinds(items) == [AttentionKind.REASON_REFUSED, AttentionKind.REASON_PENDING]
    assert [item.teacher_ids for item in items] == [(2,), (1,)]


def test_an_accepted_reason_needs_no_attention():
    """Accepted by the board: done."""
    assert (
        attention_items(0, 0, [facts(1, LoadStatus.BELOW_MINIMUM, MinimumReasonState.ACCEPTED)])
        == []
    )


def test_extra_hours_not_accepted_yet_are_an_item_and_accepted_ones_are_not():
    """Only the pending excess needs attention (D13, D96)."""
    items = attention_items(
        0,
        0,
        [
            facts(1, LoadStatus.ABOVE_MAXIMUM, extra=ExtraStatus.PENDING),
            facts(2, LoadStatus.ABOVE_MAXIMUM, extra=ExtraStatus.ACCEPTED),
        ],
    )
    assert kinds(items) == [AttentionKind.EXTRA_PENDING]
    assert items[0].teacher_ids == (1,)


def test_a_teacher_without_a_range_is_an_item():
    """A gap in the data: the manager has to define the range."""
    [item] = attention_items(0, 0, [facts(4, LoadStatus.NO_RANGE)])
    assert (item.kind, item.teacher_ids) == (AttentionKind.NO_RANGE, (4,))


def test_the_items_come_in_a_fixed_order_of_urgency():
    """Units first, then the teachers' items; the order does not depend on the input."""
    items = attention_items(
        1,
        1,
        [
            facts(4, LoadStatus.NO_RANGE),
            facts(1, LoadStatus.ABOVE_MAXIMUM, extra=ExtraStatus.PENDING),
            facts(2, LoadStatus.BELOW_MINIMUM, MinimumReasonState.MISSING),
        ],
    )
    assert kinds(items) == [
        AttentionKind.UNASSIGNED_UNITS,
        AttentionKind.STALE_UNITS,
        AttentionKind.REASON_MISSING,
        AttentionKind.EXTRA_PENDING,
        AttentionKind.NO_RANGE,
    ]


def test_the_bar_is_scaled_to_the_maximum_with_markers():
    """8 hours in a 6-12 range: filled 66.7%, minimum at 50%, maximum at the end."""
    bar = load_bar(D("8"), D("6"), D("12"))
    assert (bar.fill_percent, bar.minimum_percent, bar.maximum_percent) == (
        D("66.7"),
        D("50.0"),
        D("100.0"),
    )


def test_the_bar_grows_past_the_maximum_and_moves_the_marker_back():
    """15 hours in a 6-12 range: the bar is full and the maximum sits at 80%."""
    bar = load_bar(D("15"), D("6"), D("12"))
    assert (bar.fill_percent, bar.maximum_percent) == (D("100.0"), D("80.0"))


def test_the_bar_without_a_minimum_has_no_minimum_marker():
    """No minimum: no marker, as the range has none (D46)."""
    bar = load_bar(D("3"), None, D("12"))
    assert bar.minimum_percent is None
    assert bar.maximum_percent == D("100.0")


def test_the_bar_without_a_range_has_no_markers():
    """No range in force: only the hours."""
    bar = load_bar(D("5"), None, None)
    assert (bar.minimum_percent, bar.maximum_percent) == (None, None)
    assert bar.fill_percent == D("100.0")


def test_the_bar_of_an_empty_load_is_empty():
    """Zero hours: nothing filled, and no division by zero without a range."""
    assert load_bar(D("0"), None, None).fill_percent == D("0.0")
    assert load_bar(D("0"), D("6"), D("12")).fill_percent == D("0.0")
