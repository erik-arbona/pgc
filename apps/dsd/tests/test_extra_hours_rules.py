"""Tests for the pure rule of the accepted extra hours (T5.4).

Implements: docs/especificacao/05_dsd_regras.md – extra hours; D13, D96.
"""

from decimal import Decimal

from apps.dsd.extra_hours import ExtraStatus, assess_extra

D = Decimal


def test_without_excess_there_is_nothing_to_accept():
    """No extra hours: no state to resolve, whatever was accepted."""
    for accepted in (D("0"), D("4")):
        result = assess_extra(D("0"), accepted)
        assert result.status == ExtraStatus.NONE
        assert result.pending_hours == D("0.00")


def test_an_excess_without_acceptance_is_pending():
    """The teacher has not accepted anything: all of it is pending."""
    result = assess_extra(D("3"), D("0"))
    assert (result.status, result.pending_hours) == (ExtraStatus.PENDING, D("3.00"))


def test_an_excess_up_to_the_accepted_hours_is_accepted():
    """Accepting 4 covers an excess of 4 exactly and of less."""
    for extra in (D("4"), D("2.5")):
        result = assess_extra(extra, D("4"))
        assert result.status == ExtraStatus.ACCEPTED
        assert result.pending_hours == D("0.00")


def test_an_excess_above_the_accepted_hours_leaves_the_rest_pending():
    """Accepting 4 with an excess of 6 leaves 2 pending."""
    result = assess_extra(D("6"), D("4"))
    assert (result.status, result.pending_hours) == (ExtraStatus.PENDING, D("2.00"))
    assert result.accepted_hours == D("4.00")
