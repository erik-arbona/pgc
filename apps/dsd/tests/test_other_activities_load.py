"""Tests for the other activities in the live load of a teacher (T5.3).

Implements: docs/especificacao/05_dsd_regras.md – the range validates teaching hours only; the
preparation and the non-teaching component add to the general total; D95.
"""

# The ``world`` fixture comes from test_assignment; F811 flags every test that uses it.
# ruff: noqa: F811

from datetime import date
from decimal import Decimal

import pytest

from apps.dsd.load_facts import teacher_loads
from apps.dsd.models import OtherActivity
from apps.dsd.services import add_activity, assign_teacher, change_state
from apps.dsd.tests.test_assignment import unit_of, world  # noqa: F401

pytestmark = pytest.mark.django_db

AS_OF = date(2026, 10, 1)
D = Decimal


def open_cell(world):
    """Open the semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def load_of(world, teacher):
    """The live load of a teacher."""
    return teacher_loads(world["semester"].dsd, [teacher], AS_OF)[teacher.pk]


def activity(world, teacher, hours, semester=None, kind=OtherActivity.Kind.RESEARCH):
    """Enter an activity of some hours."""
    add_activity(
        world["manager"], teacher, semester or world["semester"], kind, "Atividade", D(hours)
    )


def test_a_teacher_without_activities_has_no_other_hours(world):
    """Zero in both semesters."""
    assert load_of(world, world["mine"]).other_hours == (D("0.00"), D("0.00"))


def test_the_activities_are_added_by_semester(world):
    """Semester 1 gets 2 + 1.5; semester 2 gets 4."""
    activity(world, world["mine"], "2")
    activity(world, world["mine"], "1.5")
    activity(world, world["mine"], "4", semester=world["semester"].dsd.semesters.get(number=2))
    assert load_of(world, world["mine"]).other_hours == (D("3.50"), D("4.00"))


def test_activities_of_other_teachers_do_not_count(world):
    """Each teacher has their own."""
    activity(world, world["mine2"], "5")
    assert load_of(world, world["mine"]).other_hours == (D("0.00"), D("0.00"))


def test_the_activities_do_not_change_the_annual_hours_nor_the_state(world):
    """The range validates the teaching hours only (spec 05)."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A", "T"), world["mine"])
    before = load_of(world, world["mine"]).assessment
    activity(world, world["mine"], "20")
    after = load_of(world, world["mine"]).assessment
    assert (after.weekly_hours, after.status) == (before.weekly_hours, before.status)


def test_the_general_total_adds_teaching_preparation_and_other_activities(world):
    """Total = teaching + preparation + other activities."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit_of(world, "A", "T"), world["mine"])
    activity(world, world["mine"], "2")
    load = load_of(world, world["mine"])
    expected = load.assessment.weekly_hours + sum(load.preparation) + D("2")
    assert load.general_total == expected.quantize(D("0.01"))
    assert load.general_total > load.assessment.weekly_hours


def test_the_load_reads_the_activities_with_a_fixed_number_of_queries(world):
    """The same queries for one or for many activities (no N+1)."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    activity(world, world["mine"], "1")
    with CaptureQueriesContext(connection) as one:
        load_of(world, world["mine"])
    for hours in ("1", "2", "3"):
        activity(world, world["mine"], hours)
    with CaptureQueriesContext(connection) as many:
        load_of(world, world["mine"])
    assert len(many) == len(one)
