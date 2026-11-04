"""Tests for the hours range column in the teacher list (T3.2, part 5).

Implements: docs/especificacao/05_dsd_regras.md – each teacher has an annual range of lesson
hours; D11, D46, D58. The list shows the range in force today.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.staff.models import Category, LoadRange, Position, Teacher, TeacherPosition
from apps.staff.tests.test_teacher_views import Setup, manager_of

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
PAST = TODAY - timedelta(days=100)
FUTURE = TODAY + timedelta(days=100)


@pytest.fixture
def a():
    """Faculty A."""
    return Setup("A")


def category_rule(maximum="14", minimum="6", valid_from=PAST):
    """Create the 'Doutor' category rule."""
    return LoadRange.objects.create(
        kind=LoadRange.Kind.CATEGORY,
        category=Category.objects.get(name="Doutor"),
        minimum_hours=Decimal(minimum),
        maximum_hours=Decimal(maximum),
        valid_from=valid_from,
    )


def page(client):
    """Return the teacher list page."""
    return client.get(reverse("staff:teacher_list")).content.decode()


def test_the_list_shows_the_minimum_and_maximum_of_a_full_time_teacher(client, a):
    """Category range 6 to 14 hours appears in the row."""
    a.teacher("A1", "Ana Silva")
    category_rule()
    manager_of(client, a.faculty)
    html = page(client)
    assert "6,00–14,00 h" in html and "Sem intervalo" not in html


def test_a_position_with_a_lower_maximum_changes_the_range_shown(client, a):
    """The lowest maximum applies, as in D11."""
    teacher = a.teacher("A1", "Ana Silva")
    chief = Position.objects.create(name="Presidente")
    TeacherPosition.objects.create(teacher=teacher, position=chief)
    category_rule(maximum="14")
    LoadRange.objects.create(
        kind=LoadRange.Kind.POSITION,
        position=chief,
        minimum_hours=Decimal("4"),
        maximum_hours=Decimal("9"),
        valid_from=PAST,
    )
    manager_of(client, a.faculty)
    html = page(client)
    assert "4,00–9,00 h" in html and "6,00–14,00" not in html


def test_a_collaborator_without_minimum_shows_only_the_maximum(client, a):
    """The collaborator range has a maximum; the minimum is optional (D46)."""
    a.teacher("C1", "Colaborador", teacher_type=Teacher.Type.HABITUAL_COLLABORATOR)
    LoadRange.objects.create(
        kind=LoadRange.Kind.TEACHER_TYPE,
        teacher_type=Teacher.Type.HABITUAL_COLLABORATOR,
        maximum_hours=Decimal("20"),
        valid_from=PAST,
    )
    manager_of(client, a.faculty)
    html = page(client)
    assert "até 20,00 h" in html


def test_a_teacher_without_any_rule_shows_no_range(client, a):
    """No rule in force is shown as a gap in the data."""
    a.teacher("A1", "Ana Silva")
    manager_of(client, a.faculty)
    assert "Sem intervalo" in page(client)


def test_a_rule_that_starts_in_the_future_is_not_shown_yet(client, a):
    """The range in force today is the one displayed."""
    a.teacher("A1", "Ana Silva")
    category_rule(valid_from=FUTURE)
    manager_of(client, a.faculty)
    assert "Sem intervalo" in page(client)


def test_an_incomplete_range_is_flagged(client, a):
    """A position with no rule is reported next to the range that exists."""
    teacher = a.teacher("A1", "Ana Silva")
    TeacherPosition.objects.create(
        teacher=teacher, position=Position.objects.create(name="Sem regra")
    )
    category_rule()
    manager_of(client, a.faculty)
    assert "incompleto" in page(client)


def test_the_htmx_fragment_also_has_the_column(client, a):
    """Filtering with HTMX keeps the range column."""
    a.teacher("A1", "Ana Silva")
    category_rule()
    manager_of(client, a.faculty)
    fragment = client.get(reverse("staff:teacher_list"), HTTP_HX_REQUEST="true").content.decode()
    assert "Intervalo" in fragment and "<html" not in fragment


def test_the_number_of_queries_does_not_grow_with_the_number_of_teachers(client, a):
    """One lookup for the whole page, not one per teacher."""
    category_rule()
    manager_of(client, a.faculty)
    a.teacher("T0", "Docente 0")
    with CaptureQueriesContext(connection) as few:
        page(client)
    for i in range(1, 15):
        a.teacher(f"T{i}", f"Docente {i}")
    with CaptureQueriesContext(connection) as many:
        page(client)
    assert len(many) == len(few)
