"""Tests for opening, closing and reopening the semesters by coordination (T2.2).

Implements: docs/backlog_fase2.md T2.2; D43 (the PGC manager opens, closes and reopens, for one
coordination or for all), D86 (any manager, whole University; skipped cells are reported).
"""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.academic.models import AcademicYear, Coordination, Faculty
from apps.core.models import AuditEntry, Profile
from apps.dsd import services
from apps.dsd.models import CoordinationSemester
from apps.dsd.services import change_state, create_dsd

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager(make_user):
    """A PGC manager."""
    return make_user(Profile.PGC_MANAGER, "mgr")


@pytest.fixture
def setup(manager):
    """A DSD for 2026 and two coordinations in two different Faculties."""
    dsd = create_dsd(AcademicYear.objects.create(start_year=2026), manager)
    coords = [
        Coordination.objects.create(
            faculty=Faculty.objects.create(name=f"F{i}", code=f"F{i}"), name=f"C{i}"
        )
        for i in (1, 2)
    ]
    return dsd, list(dsd.semesters.order_by("number")), coords


def state(semester, coordination):
    """The stored status of a cell, or ``None`` when not opened."""
    row = CoordinationSemester.objects.filter(
        dsd_semester=semester, coordination=coordination
    ).first()
    return None if row is None else row.status


# --- the model ---------------------------------------------------------------------------------


def test_a_second_state_for_the_same_cell_is_refused_by_the_database(setup):
    """One state per semester and coordination, also under concurrency."""
    _, (s1, _), (c1, _) = setup
    CoordinationSemester.objects.create(dsd_semester=s1, coordination=c1, status="open")
    with pytest.raises(IntegrityError), transaction.atomic():
        CoordinationSemester.objects.create(dsd_semester=s1, coordination=c1, status="closed")


# --- the service -------------------------------------------------------------------------------


def test_opening_one_semester_of_one_coordination(setup, manager):
    """Only that cell changes; the rest stays not opened."""
    _, (s1, s2), (c1, c2) = setup
    result = change_state(manager, "open", [s1], [c1])
    assert [state(s1, c1), state(s1, c2), state(s2, c1), state(s2, c2)] == [
        "open",
        None,
        None,
        None,
    ]
    assert result.changed == [(s1, c1)] and result.skipped == []


def test_opening_everything_covers_every_coordination_and_both_semesters(setup, manager):
    """'Open all' reaches all coordinations of the University, whatever their Faculty (D86)."""
    _, semesters, coords = setup
    result = change_state(manager, "open", semesters, coords)
    assert {state(s, c) for s in semesters for c in coords} == {"open"}
    assert len(result.changed) == 4


def test_closing_for_the_whole_university(setup, manager):
    """Close every coordination at once, with a reason."""
    _, semesters, coords = setup
    change_state(manager, "open", semesters, coords)
    change_state(manager, "close", semesters, coords, reason="end of the semester")
    assert {state(s, c) for s in semesters for c in coords} == {"closed"}


def test_reopening_a_closed_cell(setup, manager):
    """A closed cell can be opened again."""
    _, (s1, _), (c1, _) = setup
    change_state(manager, "open", [s1], [c1])
    change_state(manager, "close", [s1], [c1], reason="done")
    change_state(manager, "reopen", [s1], [c1], reason="correction")
    assert state(s1, c1) == "open"


def test_cells_where_the_action_does_not_apply_are_skipped_and_reported(setup, manager):
    """Closing a never-opened cell, or opening an open one, changes nothing and is reported."""
    _, (s1, s2), (c1, c2) = setup
    change_state(manager, "open", [s1], [c1])
    result = change_state(manager, "open", [s1, s2], [c1, c2])
    assert result.changed == [(s1, c2), (s2, c1), (s2, c2)] and result.skipped == [(s1, c1)]
    closing = change_state(manager, "close", [s1], [c1, c2], reason="x")
    assert closing.changed == [(s1, c1), (s1, c2)]
    again = change_state(manager, "close", [s1], [c1], reason="x")
    assert again.skipped == [(s1, c1)] and again.changed == []


@pytest.mark.parametrize("action", ["close", "reopen"])
def test_closing_and_reopening_need_a_reason(setup, manager, action):
    """Without a reason nothing is written."""
    _, (s1, _), (c1, _) = setup
    change_state(manager, "open", [s1], [c1])
    if action == "reopen":
        change_state(manager, "close", [s1], [c1], reason="r")
    before = state(s1, c1)
    with pytest.raises(ValidationError):
        change_state(manager, action, [s1], [c1], reason="  ")
    assert state(s1, c1) == before


def test_opening_needs_no_reason(setup, manager):
    """The first opening creates the state; a reason is optional (D40)."""
    _, (s1, _), (c1, _) = setup
    change_state(manager, "open", [s1], [c1], reason="")
    assert state(s1, c1) == "open"


def test_one_audit_entry_per_changed_cell_with_the_actor_and_the_reason(setup, manager):
    """Who, when, old and new value and why are kept for every changed cell."""
    _, semesters, coords = setup
    change_state(manager, "open", semesters, coords)
    change_state(manager, "close", semesters, coords, reason="end of the year")
    entries = AuditEntry.objects.filter(entity="dsd.coordinationsemester")
    assert entries.filter(action="create").count() == 4
    updates = entries.filter(action="update")
    assert updates.count() == 4 and {e.reason for e in updates} == {"end of the year"}
    assert {e.actor_id for e in updates} == {manager.pk}
    assert {e.old_value["status"] for e in updates} == {"open"}
    assert {e.new_value["status"] for e in updates} == {"closed"}


def test_skipped_cells_write_no_audit_entry(setup, manager):
    """Nothing changed, nothing logged."""
    _, (s1, _), (c1, _) = setup
    change_state(manager, "open", [s1], [c1])
    count = AuditEntry.objects.count()
    change_state(manager, "open", [s1], [c1])
    assert AuditEntry.objects.count() == count


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_only_a_manager_changes_states(setup, make_user, profile):
    """Coordinator, board and the others cannot open or close."""
    _, (s1, _), (c1, _) = setup
    with pytest.raises(PermissionDenied):
        change_state(make_user(profile), "open", [s1], [c1])
    assert not CoordinationSemester.objects.exists()


def test_losing_the_race_on_a_first_opening_skips_the_cell(setup, manager, monkeypatch):
    """If another manager opens the same cell at the same time, the cell is reported skipped.

    The competing insert is made just before our own save, so our save hits the unique
    constraint; the transaction of the whole change must survive that.
    """
    _, (s1, s2), (c1, _) = setup
    real = services.audited_save

    def racing(instance, actor, reason=""):
        if instance._state.adding and instance.dsd_semester_id == s1.pk:
            CoordinationSemester.objects.create(dsd_semester=s1, coordination=c1, status="open")
        return real(instance, actor, reason)

    monkeypatch.setattr(services, "audited_save", racing)
    result = change_state(manager, "open", [s1, s2], [c1])
    assert result.skipped == [(s1, c1)] and result.changed == [(s2, c1)]
    assert state(s2, c1) == "open"


# --- the screens -------------------------------------------------------------------------------


def test_the_grid_shows_each_state_to_manager_and_coordinator(client, setup, manager, make_user):
    """'Not opened', 'open' and 'closed' appear per coordination and semester."""
    dsd, (s1, s2), (c1, c2) = setup
    change_state(manager, "open", [s1, s2], [c1])
    change_state(manager, "close", [s2], [c1], reason="r")
    url = reverse("dsd:dsd_detail", args=[dsd.pk])
    for profile in (Profile.PGC_MANAGER, Profile.COORDINATOR):
        client.force_login(make_user(profile, f"u-{profile}"))
        page = client.get(url).content.decode()
        assert "aberto" in page and "fechado" in page and "não aberto" in page


def test_the_coordinator_does_not_see_the_link_to_change_states(client, setup, make_user):
    """Only the manager is offered the form."""
    dsd, _, _ = setup
    url = reverse("dsd:dsd_detail", args=[dsd.pk])
    client.force_login(make_user(Profile.COORDINATOR, "c"))
    assert reverse("dsd:dsd_state", args=[dsd.pk]) not in client.get(url).content.decode()


def test_the_manager_opens_everything_from_the_form(client, setup, manager):
    """Action open, both semesters, all coordinations."""
    dsd, semesters, coords = setup
    client.force_login(manager)
    response = client.post(
        reverse("dsd:dsd_state", args=[dsd.pk]),
        {"action": "open", "semester": "both", "coordination": "", "reason": ""},
    )
    assert response.status_code == 302
    assert {state(s, c) for s in semesters for c in coords} == {"open"}


def test_the_manager_closes_one_coordination_from_the_form(client, setup, manager):
    """Action close, semester 1 only, one coordination, with a reason."""
    dsd, (s1, s2), (c1, c2) = setup
    change_state(manager, "open", [s1, s2], [c1, c2])
    client.force_login(manager)
    client.post(
        reverse("dsd:dsd_state", args=[dsd.pk]),
        {"action": "close", "semester": "1", "coordination": c1.pk, "reason": "done"},
    )
    assert [state(s1, c1), state(s2, c1), state(s1, c2), state(s2, c2)] == [
        "closed",
        "open",
        "open",
        "open",
    ]


def test_closing_from_the_form_without_a_reason_shows_an_error(client, setup, manager):
    """The form asks for the reason and writes nothing."""
    dsd, (s1, _), (c1, _) = setup
    change_state(manager, "open", [s1], [c1])
    client.force_login(manager)
    response = client.post(
        reverse("dsd:dsd_state", args=[dsd.pk]),
        {"action": "close", "semester": "1", "coordination": c1.pk, "reason": ""},
    )
    assert response.status_code == 200 and state(s1, c1) == "open"


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403_on_the_state_form(client, setup, make_user, profile):
    """Also for a DSD that does not exist: nobody learns what exists (403, not 404)."""
    dsd, _, _ = setup
    client.force_login(make_user(profile))
    assert client.get(reverse("dsd:dsd_state", args=[dsd.pk])).status_code == 403
    assert client.get(reverse("dsd:dsd_state", args=[dsd.pk + 999])).status_code == 403
    assert (
        client.post(reverse("dsd:dsd_state", args=[dsd.pk]), {"action": "open"}).status_code == 403
    )
    assert not CoordinationSemester.objects.exists()


def test_the_other_profiles_do_not_read_the_grid(client, setup, make_user):
    """The grid needs ``dsd.view``."""
    dsd, _, _ = setup
    client.force_login(make_user(Profile.TEACHER, "t"))
    assert client.get(reverse("dsd:dsd_detail", args=[dsd.pk])).status_code == 403


def test_anonymous_visitors_are_redirected_to_login(client, setup):
    """Both screens require a session."""
    dsd, _, _ = setup
    for name in ("dsd:dsd_detail", "dsd:dsd_state"):
        response = client.get(reverse(name, args=[dsd.pk]))
        assert response.status_code == 302 and "/accounts/login/" in response["Location"]
