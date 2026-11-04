"""Tests for the assignment by subject: highlights and the inline teacher selector (T6.2).

Implements: docs/especificacao/07_arquitetura.md – assignment by subject; D20, D50 (forms that
work without JavaScript, HTMX only to update parts), D94 (one teacher per unit), D40, D54, D86.
"""

# The fixtures come from other test modules; F811 flags every test that uses them.
# ruff: noqa: F811

from html.parser import HTMLParser

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.academic.models import ClassType, SubjectClassLoad
from apps.dsd.services import assign_teacher
from apps.dsd.tests.test_assignment import make_teacher, unit_of, world  # noqa: F401
from apps.dsd.tests.test_below_minimum import board, open_cell  # noqa: F401

pytestmark = pytest.mark.django_db

HX = {"HTTP_HX_REQUEST": "true"}


def page_url(world):
    """The page of the offering."""
    return reverse("dsd:offering_detail", args=[world["offering"].pk])


def inline_url(world, unit):
    """The endpoint that gives a teacher to a unit from its row."""
    return reverse("dsd:unit_teacher_inline", args=[world["offering"].pk, unit.pk])


def post(client, world, unit, teacher=None, seen="default", hx=True):
    """Choose a teacher in the row of a unit (with the unit's version unless told otherwise)."""
    data = {"teacher": teacher.pk if teacher else ""}
    if seen == "default":
        seen = unit.version
    if seen is not None:
        data["seen"] = seen
    return client.post(inline_url(world, unit), data, **(HX if hx else {}))


def test_the_units_without_a_teacher_are_marked_and_counted(board, client):
    """Four units and nobody yet: the page says so and marks every row."""
    open_cell(board)
    client.force_login(board["coordinator"])
    html = client.get(page_url(board)).content.decode()
    assert html.count('class="unassigned"') == 4
    assert "4 de 4" in html


def test_assigning_a_teacher_lowers_the_count(board, client):
    """One of the four is given."""
    open_cell(board)
    assign_teacher(board["coordinator"], unit_of(board, "A", "T"), board["mine"])
    client.force_login(board["coordinator"])
    html = client.get(page_url(board)).content.decode()
    assert html.count('class="unassigned"') == 3
    assert "3 de 4" in html


def test_obsolete_units_are_not_counted_as_to_assign(board, client):
    """The plan drops practice: the two P units are obsolete, two T units remain to assign."""
    SubjectClassLoad.objects.filter(class_type=ClassType.objects.get(code="P")).delete()
    open_cell(board)
    client.force_login(board["coordinator"])
    html = client.get(page_url(board)).content.decode()
    assert html.count('class="unassigned"') == 2
    assert "2 de 2" in html


def test_the_selector_lists_the_active_teachers_of_the_coordination_with_their_load(board, client):
    """T1 and T2 only (not the foreign one, not the inactive one), each with hours and state."""
    open_cell(board)
    client.force_login(board["coordinator"])
    html = client.get(page_url(board)).content.decode()
    assert '<select name="teacher"' in html
    assert board["mine"].name in html and board["mine2"].name in html
    assert board["foreign"].name not in html
    assert board["inactive"].name not in html
    assert "abaixo do mínimo" in html


def test_the_selector_follows_the_cell(board, client):
    """Not opened: the coordinator has none; the manager does; the teacher account never (D86)."""
    client.force_login(board["coordinator"])
    assert '<select name="teacher"' not in client.get(page_url(board)).content.decode()
    client.force_login(board["manager"])
    assert '<select name="teacher"' in client.get(page_url(board)).content.decode()


def test_a_unit_with_a_teacher_has_no_selector(board, client):
    """Changing a teacher needs a reason (D40), so it stays on the form page."""
    open_cell(board)
    for unit in [unit_of(board, label, kind) for label in "AB" for kind in "TP"]:
        assign_teacher(board["coordinator"], unit, board["mine"])
    client.force_login(board["coordinator"])
    html = client.get(page_url(board)).content.decode()
    assert '<select name="teacher"' not in html
    assert board["mine"].name in html


def test_choosing_a_teacher_in_the_row_assigns_and_returns_only_that_row(board, client):
    """HTMX: the response is the updated row, not the whole page."""
    open_cell(board)
    unit = unit_of(board, "A", "T")
    client.force_login(board["coordinator"])
    response = post(client, board, unit, board["mine"])
    assert response.status_code == 200
    html = response.content.decode()
    assert f'id="unit-{unit.pk}"' in html
    assert board["mine"].name in html
    assert "<html" not in html
    unit.refresh_from_db()
    assert unit.teacher == board["mine"]


def test_without_htmx_the_same_form_saves_and_goes_back_to_the_page(board, client):
    """D50: it works without JavaScript."""
    open_cell(board)
    unit = unit_of(board, "A", "T")
    client.force_login(board["coordinator"])
    response = post(client, board, unit, board["mine"], hx=False)
    assert response.status_code == 302
    assert response.url == page_url(board)
    unit.refresh_from_db()
    assert unit.teacher == board["mine"]


def test_errors_are_shown_in_the_row_and_nothing_is_saved(board, client):
    """No teacher chosen, a teacher of another coordination, an old version, a missing version."""
    open_cell(board)
    unit = unit_of(board, "A", "T")
    client.force_login(board["coordinator"])
    for teacher, seen in (
        (None, "default"),
        (board["foreign"], "default"),
        (board["inactive"], "default"),
        (board["mine"], unit.version + 5),
        (board["mine"], None),
    ):
        response = post(client, board, unit, teacher, seen)
        assert response.status_code == 200
        assert 'class="error"' in response.content.decode()
        unit.refresh_from_db()
        assert unit.teacher is None


def test_the_row_shows_the_error_of_a_cell_that_is_not_open(board, client):
    """Not opened for the coordinator: the service refuses and the row says why (D86)."""
    unit = unit_of(board, "A", "T")
    client.force_login(board["coordinator"])
    response = post(client, board, unit, board["mine"])
    assert response.status_code == 200
    assert 'class="error"' in response.content.decode()
    unit.refresh_from_db()
    assert unit.teacher is None


def test_a_unit_that_already_has_a_teacher_is_not_replaced_from_the_row(board, client):
    """Replacing needs a reason (D40): the row refuses and points to the form."""
    open_cell(board)
    unit = unit_of(board, "A", "T")
    assign_teacher(board["coordinator"], unit, board["mine"])
    unit.refresh_from_db()
    client.force_login(board["coordinator"])
    response = post(client, board, unit, board["mine2"])
    assert 'class="error"' in response.content.decode()
    unit.refresh_from_db()
    assert unit.teacher == board["mine"]


def test_other_coordinators_and_teacher_accounts_get_403(board, client):
    """Scope by coordination and profile on the inline endpoint (D69)."""
    open_cell(board)
    unit = unit_of(board, "A", "T")
    for user in (board["other_coordinator"], board["teacher_user"]):
        client.force_login(user)
        assert post(client, board, unit, board["mine"]).status_code == 403
        # Even a request that would fail validation is refused first: the permission comes
        # before any check of the data, so nothing is learned from the error text.
        assert post(client, board, unit, None).status_code == 403
    unit.refresh_from_db()
    assert unit.teacher is None


def test_the_endpoint_needs_a_session_and_refuses_get(board, client):
    """Anonymous users go to the login; the endpoint only takes POST."""
    unit = unit_of(board, "A", "T")
    assert post(client, board, unit, board["mine"]).status_code == 302
    client.force_login(board["coordinator"])
    assert client.get(inline_url(board, unit)).status_code == 405


def test_the_page_reads_a_fixed_number_of_queries_whatever_the_candidates(board, client):
    """More teachers in the coordination do not mean more queries (no N+1)."""
    open_cell(board)
    client.force_login(board["coordinator"])
    client.get(page_url(board))  # warm the caches that are not about the teachers
    with CaptureQueriesContext(connection) as before:
        client.get(page_url(board))
    for index in range(5, 10):
        make_teacher(board["coordination"], f"T{index}")
    with CaptureQueriesContext(connection) as after:
        client.get(page_url(board))
    assert len(after) == len(before)


class _FormDepth(HTMLParser):
    """Record whether a <form> is ever opened inside another one."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.nested = False

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            self.nested = self.nested or self.depth > 0
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "form":
            self.depth -= 1


def test_the_page_has_no_form_inside_another_form(board, client):
    """The selector's form must not sit inside the merge form: the browser would drop it.

    A nested form is invalid HTML and the parser ignores the inner tag, so the selector would
    do nothing and the fallback button would submit the merge form (review of T6.2).
    """
    open_cell(board)
    client.force_login(board["coordinator"])
    html = client.get(page_url(board)).content.decode()
    parser = _FormDepth()
    parser.feed(html)
    assert not parser.nested
    assert 'hx-post="' in html
    assert "{#" not in html and "#}" not in html  # a template comment must not show


def test_the_merge_checkboxes_and_button_belong_to_the_merge_form(board, client):
    """With the merge form closed before the table, its fields point to it by id."""
    open_cell(board)
    client.force_login(board["coordinator"])
    html = client.get(page_url(board)).content.decode()
    assert 'id="merge-form"' in html
    assert html.count('name="units"') == html.count('name="units" value') > 0
    assert html.count('form="merge-form"') >= html.count('name="units"') + 1


def test_a_unit_that_vanishes_during_the_request_refreshes_the_page(board, client, monkeypatch):
    """Another user deleted the unit (groups changed): ask HTMX to reload, not a 500."""
    from django.core.exceptions import ValidationError

    from apps.dsd.models import TeachingUnit, TeachingUnitMember

    open_cell(board)
    unit = unit_of(board, "A", "T")

    def vanish(actor, target, teacher, reason, seen):
        TeachingUnitMember.objects.filter(unit=target).delete()
        TeachingUnit.objects.filter(pk=target.pk).delete()
        raise ValidationError("stale")

    monkeypatch.setattr("apps.dsd.views.assign_teacher", vanish)
    client.force_login(board["coordinator"])
    response = post(client, board, unit, board["mine"])
    assert response.status_code == 200
    assert response.headers["HX-Refresh"] == "true"
