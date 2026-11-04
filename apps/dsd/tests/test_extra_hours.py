"""Tests for recording the extra hours a teacher accepts (T5.4).

Implements: docs/backlog_fase2.md T5.4; D13 (extra hours only with the teacher acceptance,
recorded by the coordinator), D96, D86 (cell), D69 (scope), D40 (reason), D54 (versions).
"""

# The ``world`` fixture comes from test_assignment; F811 flags every test that uses it.
# ruff: noqa: F811

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.models import AuditEntry
from apps.dsd.extra_hours import ExtraStatus
from apps.dsd.load_facts import teacher_loads
from apps.dsd.models import AcceptedExtraHours
from apps.dsd.services import (
    change_state,
    clear_accepted_extra,
    set_accepted_extra,
)
from apps.dsd.tests.test_assignment import world  # noqa: F401

pytestmark = pytest.mark.django_db

D = Decimal


def open_cell(world, number=1):
    """Open a semester for the coordination."""
    semester = world["semester"].dsd.semesters.get(number=number)
    change_state(world["manager"], "open", [semester], [world["coordination"]])


def accept(world, hours="4", user=None, teacher=None, **kwargs):
    """Record that the teacher accepts some extra hours."""
    return set_accepted_extra(
        user or world["coordinator"],
        teacher or world["mine"],
        world["semester"].dsd,
        D(hours),
        **kwargs,
    )


def test_the_coordinator_records_the_accepted_hours(world):
    """One record per teacher and DSD, with the hours."""
    open_cell(world)
    accept(world)
    record = AcceptedExtraHours.objects.get()
    assert (record.teacher, record.dsd, record.hours) == (
        world["mine"],
        world["semester"].dsd,
        D("4.00"),
    )
    assert record.coordination == world["coordination"]


def test_recording_is_audited(world):
    """Who, what and when (rule 7)."""
    open_cell(world)
    accept(world)
    assert AuditEntry.objects.get(entity="dsd.acceptedextrahours").actor == world["coordinator"]


def test_the_hours_must_be_positive(world):
    """Zero or negative: remove the record instead."""
    open_cell(world)
    for hours in ("0", "-1"):
        with pytest.raises(ValidationError):
            accept(world, hours)
    assert AcceptedExtraHours.objects.count() == 0


def test_changing_the_hours_needs_a_reason_and_keeps_one_record(world):
    """The second call updates the record; the reason is required then (D40)."""
    open_cell(world)
    record = accept(world)
    with pytest.raises(ValidationError):
        accept(world, "6", seen_version=record.version)
    accept(world, "6", reason="Mais horas", seen_version=record.version)
    assert AcceptedExtraHours.objects.get().hours == D("6.00")
    entry = AuditEntry.objects.filter(entity="dsd.acceptedextrahours").latest("pk")
    assert entry.old_value["hours"] == "4.00"


def test_changing_with_an_old_version_is_refused(world):
    """Optimistic lock (D54)."""
    open_cell(world)
    record = accept(world)
    accept(world, "5", reason="r", seen_version=record.version)
    with pytest.raises(ValidationError):
        accept(world, "6", reason="r", seen_version=record.version)
    assert AcceptedExtraHours.objects.get().hours == D("5.00")


def test_clearing_needs_a_reason_and_a_current_version(world):
    """The deletion is audited with its reason."""
    open_cell(world)
    record = accept(world)
    with pytest.raises(ValidationError):
        clear_accepted_extra(world["coordinator"], record, "", record.version)
    with pytest.raises(ValidationError):
        clear_accepted_extra(world["coordinator"], record, "x", 99)
    clear_accepted_extra(world["coordinator"], record, "Já não aceita", record.version)
    assert AcceptedExtraHours.objects.count() == 0
    assert AuditEntry.objects.filter(entity="dsd.acceptedextrahours", action="delete").exists()


def test_scope_and_profile_are_checked(world):
    """Another coordination and a teacher account are refused."""
    open_cell(world)
    for user in (world["other_coordinator"], world["teacher_user"]):
        with pytest.raises(PermissionDenied):
            accept(world, user=user)


def test_only_active_teachers_of_the_coordination_can_accept(world):
    """A foreign teacher is out of scope; an inactive one is refused."""
    open_cell(world)
    with pytest.raises(PermissionDenied):
        accept(world, teacher=world["foreign"])
    with pytest.raises(ValidationError):
        accept(world, teacher=world["inactive"])


def test_a_stale_teacher_copy_cannot_write_in_the_old_cell(world):
    """The teacher moved after the caller loaded them: refused (as the other activities)."""
    open_cell(world)
    stale = world["mine"]
    type(stale).objects.filter(pk=stale.pk).update(coordination=world["foreign"].coordination)
    with pytest.raises(ValidationError):
        accept(world, teacher=stale)
    assert AcceptedExtraHours.objects.count() == 0


def test_the_year_can_be_written_while_one_of_its_semesters_is_open(world):
    """The record belongs to the year: it is writable if either semester is (D96)."""
    open_cell(world, number=2)
    accept(world)
    assert AcceptedExtraHours.objects.count() == 1


def test_not_opened_only_the_manager_writes(world):
    """No semester opened for the coordination: only the manager (D86)."""
    with pytest.raises(ValidationError):
        accept(world)
    accept(world, user=world["manager"])
    assert AcceptedExtraHours.objects.count() == 1


def test_nobody_writes_when_both_semesters_are_closed(world):
    """Closed in the two semesters: read only (D86)."""
    open_cell(world, 1)
    open_cell(world, 2)
    record = accept(world)
    for number in (1, 2):
        semester = world["semester"].dsd.semesters.get(number=number)
        change_state(world["manager"], "close", [semester], [world["coordination"]], reason="fim")
    with pytest.raises(ValidationError):
        accept(world, "5", user=world["manager"], reason="r", seen_version=record.version)
    with pytest.raises(ValidationError):
        clear_accepted_extra(world["manager"], record, "r", record.version)
    assert AcceptedExtraHours.objects.get().hours == D("4.00")


def test_the_live_load_carries_the_acceptance(world):
    """Without an excess the status is none; the record is kept and its hours are shown."""
    open_cell(world)
    accept(world)
    loads = teacher_loads(world["semester"].dsd, [world["mine"]], date(2026, 10, 1))
    load = loads[world["mine"].pk]
    assert load.extra.accepted_hours == D("4.00")
    assert load.extra.status == ExtraStatus.NONE
