"""Tests for the other activities of a teacher (T5.3).

Implements: docs/backlog_fase2.md T5.3; D15 (non-teaching component entered by the coordinator),
D95, D86 (state of the cell), D69 (coordination scope), D40 (reason), D54 (versions).
"""

# The ``world`` fixture comes from test_assignment; F811 flags every test that uses it.
# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError

from apps.core.models import AuditEntry
from apps.dsd.models import OtherActivity
from apps.dsd.services import (
    add_activity,
    change_state,
    edit_activity,
    remove_activity,
)
from apps.dsd.tests.test_assignment import make_teacher, world  # noqa: F401

pytestmark = pytest.mark.django_db

KIND = OtherActivity.Kind.RESEARCH


def open_cell(world):
    """Open the semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def add(world, user=None, teacher=None, **overrides):
    """Add a valid activity (3 hours of research) for a teacher of the coordination."""
    values = {
        "kind": KIND,
        "description": "Projeto X",
        "weekly_hours": Decimal("3"),
    }
    values.update(overrides)
    return add_activity(
        user or world["coordinator"],
        teacher or world["mine"],
        world["semester"],
        **values,
    )


def test_the_coordinator_adds_an_activity_to_a_teacher_of_the_coordination(world):
    """Type, description and hours are stored for the teacher and the semester."""
    open_cell(world)
    activity = add(world)
    stored = OtherActivity.objects.get()
    assert (stored.teacher, stored.dsd_semester, stored.kind) == (
        world["mine"],
        world["semester"],
        KIND,
    )
    assert (stored.description, stored.weekly_hours) == ("Projeto X", Decimal("3.00"))
    assert activity.pk == stored.pk


def test_adding_an_activity_is_audited(world):
    """Who, what and when are recorded (rule 7)."""
    open_cell(world)
    add(world)
    entry = AuditEntry.objects.get(entity="dsd.otheractivity")
    assert entry.actor == world["coordinator"]


def test_a_teacher_can_have_several_activities_in_the_same_semester(world):
    """No limit on the number; the hours add up elsewhere."""
    open_cell(world)
    add(world)
    add(world, description="Gestão", kind=OtherActivity.Kind.MANAGEMENT)
    assert OtherActivity.objects.count() == 2


def test_the_hours_must_be_positive(world):
    """Zero or negative hours are refused."""
    open_cell(world)
    for hours in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValidationError):
            add(world, weekly_hours=hours)
    assert OtherActivity.objects.count() == 0


def test_the_description_is_required(world):
    """A blank description is refused."""
    open_cell(world)
    with pytest.raises(ValidationError):
        add(world, description="   ")


def test_only_active_teachers_of_the_coordination_get_new_activities(world):
    """Foreign and inactive teachers are refused (D69)."""
    open_cell(world)
    for teacher in (world["foreign"], world["inactive"]):
        with pytest.raises((ValidationError, PermissionDenied)):
            add(world, teacher=teacher)
    assert OtherActivity.objects.count() == 0


def test_a_coordinator_of_another_coordination_cannot_add(world):
    """Scope by coordination."""
    open_cell(world)
    with pytest.raises(PermissionDenied):
        add(world, user=world["other_coordinator"])


def test_users_without_the_action_cannot_add(world):
    """A teacher account only reads."""
    open_cell(world)
    with pytest.raises(PermissionDenied):
        add(world, user=world["teacher_user"])


def test_the_manager_adds_before_the_cell_is_opened_and_the_coordinator_cannot(world):
    """Not opened: only the manager prepares (D86)."""
    with pytest.raises(ValidationError):
        add(world)
    add(world, user=world["manager"])
    assert OtherActivity.objects.count() == 1


def test_nobody_adds_in_a_closed_cell(world):
    """Closed: read only (D86)."""
    open_cell(world)
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="fim"
    )
    with pytest.raises(ValidationError):
        add(world, user=world["manager"])


def test_saving_outside_dsd_write_fails(world):
    """The write guard covers the model (D86)."""
    with pytest.raises(ImproperlyConfigured):
        OtherActivity.objects.create(
            dsd_semester=world["semester"],
            teacher=world["mine"],
            coordination=world["coordination"],
            kind=KIND,
            description="x",
            weekly_hours=Decimal("1"),
        )


def test_editing_needs_a_reason_and_is_audited(world):
    """Changing hours keeps the old value in the audit (rule 7, D40)."""
    open_cell(world)
    activity = add(world)
    with pytest.raises(ValidationError):
        edit_activity(
            world["coordinator"],
            activity,
            kind=KIND,
            description="Projeto X",
            weekly_hours=Decimal("4"),
            reason="",
            seen_version=activity.version,
        )
    edit_activity(
        world["coordinator"],
        activity,
        kind=KIND,
        description="Projeto X",
        weekly_hours=Decimal("4"),
        reason="Mais horas",
        seen_version=activity.version,
    )
    assert OtherActivity.objects.get().weekly_hours == Decimal("4.00")
    entry = AuditEntry.objects.filter(entity="dsd.otheractivity").latest("pk")
    assert entry.reason == "Mais horas"
    assert entry.old_value["weekly_hours"] == "3.00"


def test_editing_with_an_old_version_is_refused(world):
    """Optimistic lock (D54)."""
    open_cell(world)
    activity = add(world)
    edit_activity(
        world["coordinator"],
        activity,
        kind=KIND,
        description="A",
        weekly_hours=Decimal("4"),
        reason="r",
        seen_version=activity.version,
    )
    with pytest.raises(ValidationError):
        edit_activity(
            world["coordinator"],
            activity,
            kind=KIND,
            description="B",
            weekly_hours=Decimal("5"),
            reason="r",
            seen_version=activity.version,
        )
    assert OtherActivity.objects.get().description == "A"


def test_removing_needs_a_reason_and_a_current_version(world):
    """The deletion is audited with its reason."""
    open_cell(world)
    activity = add(world)
    with pytest.raises(ValidationError):
        remove_activity(world["coordinator"], activity, reason=" ", seen_version=activity.version)
    with pytest.raises(ValidationError):
        remove_activity(world["coordinator"], activity, reason="x", seen_version=99)
    remove_activity(world["coordinator"], activity, reason="Já não se aplica", seen_version=1)
    assert OtherActivity.objects.count() == 0
    assert AuditEntry.objects.filter(entity="dsd.otheractivity", action="delete").exists()


def test_a_closed_cell_blocks_editing_and_removing(world):
    """Closed: read only."""
    open_cell(world)
    activity = add(world)
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="fim"
    )
    with pytest.raises(ValidationError):
        edit_activity(
            world["manager"],
            activity,
            kind=KIND,
            description="x",
            weekly_hours=Decimal("1"),
            reason="r",
            seen_version=activity.version,
        )
    with pytest.raises(ValidationError):
        remove_activity(world["manager"], activity, reason="r", seen_version=activity.version)
    assert OtherActivity.objects.count() == 1


def test_a_teacher_with_activities_cannot_be_deleted(world):
    """The teacher is protected (T0.5)."""
    from django.db.models import ProtectedError

    open_cell(world)
    add(world)
    with pytest.raises(ProtectedError):
        world["mine"].delete()
