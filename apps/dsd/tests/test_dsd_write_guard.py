"""Tests for the write guard of the DSD data (T2.2).

Implements: docs/backlog_fase2.md T2.2; D43, D86 – the state is enforced on every write: a
closed cell is read-only for everybody; a not-yet-opened cell only takes writes from who may
change the state; an open cell takes writes from who the action allows for that coordination.
"""

import pytest
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError

from apps.academic.models import AcademicYear, Coordination, Faculty
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.core.permissions import PermissionRegistry
from apps.dsd.lifecycle import GuardedDsdWrites, dsd_write
from apps.dsd.models import CoordinationSemester
from apps.dsd.services import change_state, create_dsd

pytestmark = pytest.mark.django_db

# The models that hold the state itself are the only ones exempt from the guard.
EXEMPT = {"Dsd", "DsdSemester", "CoordinationSemester"}


@pytest.fixture
def reg() -> PermissionRegistry:
    """An isolated registry with the scoped write action the guard will check."""
    registry = PermissionRegistry()
    registry.register(
        "t.assign", {Profile.COORDINATOR, Profile.PGC_MANAGER}, write=True, scoped=True
    )
    return registry


@pytest.fixture
def world(django_user_model):
    """A DSD, one coordination, its coordinator and a manager of its Faculty."""
    faculty = Faculty.objects.create(name="F", code="F")
    coordination = Coordination.objects.create(faculty=faculty, name="C")
    other = Coordination.objects.create(faculty=faculty, name="D")
    coordinator = django_user_model.objects.create_user(username="coord", password="x")
    RoleAssignment.objects.create(
        user=coordinator,
        profile=Profile.COORDINATOR,
        scope_kind=ScopeKind.COORDINATION,
        scope_id=coordination.pk,
    )
    manager = django_user_model.objects.create_user(username="mgr", password="x")
    RoleAssignment.objects.create(
        user=manager, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.FACULTY, scope_id=faculty.pk
    )
    dsd = create_dsd(AcademicYear.objects.create(start_year=2026), manager)
    semester = dsd.semesters.get(number=1)
    return {
        "semester": semester,
        "coordination": coordination,
        "other": other,
        "coordinator": coordinator,
        "manager": manager,
    }


def enter(world, reg, who, coordination=None):
    """Run an empty write block as ``who`` on the cell and return nothing."""
    coordination = coordination or world["coordination"]
    with dsd_write(
        world[who], "t.assign", world["semester"], coordination.pk, permission_registry=reg
    ):
        pass


def set_state(world, action, reason=""):
    """Move the main cell with the real service."""
    change_state(world["manager"], action, [world["semester"]], [world["coordination"]], reason)


def test_an_open_cell_accepts_the_coordinator(world, reg):
    """The coordinator writes while the cell is open."""
    set_state(world, "open")
    enter(world, reg, "coordinator")


def test_a_closed_cell_refuses_everybody_with_a_clear_message(world, reg):
    """Closed means read-only, also for the manager (D86)."""
    set_state(world, "open")
    set_state(world, "close", "done")
    for who in ("coordinator", "manager"):
        with pytest.raises(ValidationError) as error:
            enter(world, reg, who)
        assert "fechado" in error.value.messages[0] and "2026-2027" in error.value.messages[0]


def test_a_cell_not_opened_refuses_the_coordinator(world, reg):
    """Before the first opening the coordinator cannot write."""
    with pytest.raises(ValidationError) as error:
        enter(world, reg, "coordinator")
    assert "ainda não foi aberto" in error.value.messages[0]


def test_a_cell_not_opened_accepts_the_manager(world, reg):
    """The manager prepares the semester (offerings) before opening it."""
    enter(world, reg, "manager")


def test_reopening_lets_the_coordinator_write_again(world, reg):
    """Reopen restores the writes."""
    set_state(world, "open")
    set_state(world, "close", "done")
    set_state(world, "reopen", "correction")
    enter(world, reg, "coordinator")


def test_a_coordinator_of_another_coordination_is_denied_even_if_open(world, reg):
    """The state does not replace the scope check (D69)."""
    change_state(world["manager"], "open", [world["semester"]], [world["other"]])
    with pytest.raises(PermissionDenied):
        enter(world, reg, "coordinator", coordination=world["other"])


def test_the_state_of_another_coordination_does_not_matter(world, reg):
    """Closing one coordination leaves the others writable."""
    change_state(
        world["manager"], "open", [world["semester"]], [world["other"], world["coordination"]]
    )
    change_state(world["manager"], "close", [world["semester"]], [world["other"]], reason="x")
    enter(world, reg, "coordinator")


# --- the mixin ---------------------------------------------------------------------------------


class _Base:
    """Stands in for ``models.Model``: records the calls that reach the database."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def save(self, *args, **kwargs) -> None:
        self.calls.append("save")

    def delete(self, *args, **kwargs) -> None:
        self.calls.append("delete")


class _Guarded(GuardedDsdWrites, _Base):
    """A record of the main cell of the ``world`` fixture."""

    def __init__(self, cell: tuple[int, int]) -> None:
        super().__init__()
        self.cell = cell

    def dsd_cell(self) -> tuple[int, int]:
        return self.cell


def test_a_guarded_record_refuses_to_save_outside_the_guard(world):
    """A write that skips ``dsd_write`` fails loudly instead of ignoring the state."""
    record = _Guarded((world["semester"].pk, world["coordination"].pk))
    for method in (record.save, record.delete):
        with pytest.raises(ImproperlyConfigured):
            method()
    assert record.calls == []


def test_a_guarded_record_saves_and_deletes_inside_the_guard_of_its_cell(world, reg):
    """Inside ``dsd_write`` for the same cell the calls reach the database."""
    set_state(world, "open")
    record = _Guarded((world["semester"].pk, world["coordination"].pk))
    with dsd_write(
        world["coordinator"],
        "t.assign",
        world["semester"],
        world["coordination"].pk,
        permission_registry=reg,
    ):
        record.save()
        record.delete()
    assert record.calls == ["save", "delete"]


def test_the_guard_of_one_cell_does_not_cover_another(world, reg):
    """A write inside the guard of one coordination cannot touch the data of another."""
    set_state(world, "open")
    other_record = _Guarded((world["semester"].pk, world["other"].pk))
    with dsd_write(
        world["coordinator"],
        "t.assign",
        world["semester"],
        world["coordination"].pk,
        permission_registry=reg,
    ):
        with pytest.raises(ImproperlyConfigured):
            other_record.save()


def test_the_guard_does_not_stay_active_after_the_block(world, reg):
    """Once the block ends, saving is refused again."""
    set_state(world, "open")
    record = _Guarded((world["semester"].pk, world["coordination"].pk))
    enter(world, reg, "coordinator")
    with pytest.raises(ImproperlyConfigured):
        record.save()


def test_every_dsd_model_holding_data_is_guarded():
    """A model added to the app after T2.2 must inherit the guard, or this test fails.

    Only the DSD, its semesters and the state itself are exempt, because they are written by
    the use cases of the state, not by the distribution (D86).
    """
    unguarded = [
        model.__name__
        for model in apps.get_app_config("dsd").get_models()
        if model.__name__ not in EXEMPT and not issubclass(model, GuardedDsdWrites)
    ]
    assert unguarded == []
    assert CoordinationSemester.__name__ in EXEMPT
