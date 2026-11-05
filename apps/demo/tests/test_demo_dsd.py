"""Tests for the DSD scenario of the fictitious data (T8.1).

Implements: docs/dados_ficticios.md; docs/backlog_fase2.md T8.1; D65. The scenario must put the
eight teachers in eight different situations of the live load, so that every state can be seen
on the screens; it must be safe to load twice and must never override what a person has done.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.academic.models import AcademicYear
from apps.core.models import AuditEntry
from apps.dsd.below_minimum import MinimumReasonState
from apps.dsd.extra_hours import ExtraStatus
from apps.dsd.load_facts import teacher_loads
from apps.dsd.load_status import LoadStatus
from apps.dsd.models import (
    AcceptedExtraHours,
    BelowMinimumReason,
    BelowMinimumReview,
    CoordinationSemester,
    Dsd,
    Offering,
    OtherActivity,
    TeachingUnit,
)
from apps.staff.models import Teacher

pytestmark = pytest.mark.django_db

D = Decimal
AS_OF = date(2026, 11, 5)


@pytest.fixture
def loaded(settings):
    """Load the demo data with DEBUG on (as in development) and return the command output."""
    settings.DEBUG = True
    out = StringIO()
    call_command("load_demo_data", stdout=out)
    return out.getvalue()


def load_of(identifier):
    """The live load of a demo teacher in the demo DSD."""
    dsd = Dsd.objects.get()
    teacher = Teacher.objects.get(identifier=identifier)
    return teacher_loads(dsd, [teacher], AS_OF)[teacher.pk]


def test_the_demo_dsd_exists_with_offerings_in_both_semesters(loaded):
    """One DSD for the demo year, and offerings generated for each of its semesters."""
    dsd = Dsd.objects.get()
    assert dsd.academic_year == AcademicYear.objects.get(start_year=2026)
    for semester in dsd.semesters.all():
        assert Offering.objects.filter(dsd_semester=semester).exists()


def test_the_first_semester_is_open_for_every_coordination(loaded):
    """So the coordinator of the demo can already work (D43, D86)."""
    first = Dsd.objects.get().semesters.get(number=1)
    states = CoordinationSemester.objects.filter(dsd_semester=first)
    assert states.count() == 4
    assert {state.status for state in states} == {CoordinationSemester.Status.OPEN}


# (teacher, state of the annual load, state of the reason below the minimum, extra hours)
SITUATIONS = [
    ("DT001", LoadStatus.BELOW_MINIMUM, MinimumReasonState.REFUSED, ExtraStatus.NONE),
    ("DT002", LoadStatus.ABOVE_MAXIMUM, MinimumReasonState.NOT_NEEDED, ExtraStatus.ACCEPTED),
    ("DT003", LoadStatus.BELOW_MINIMUM, MinimumReasonState.ACCEPTED, ExtraStatus.NONE),
    ("DT004", LoadStatus.BELOW_MINIMUM, MinimumReasonState.MISSING, ExtraStatus.NONE),
    ("DT005", LoadStatus.BELOW_MINIMUM, MinimumReasonState.PENDING, ExtraStatus.NONE),
    ("DT006", LoadStatus.AT_MAXIMUM, MinimumReasonState.NOT_NEEDED, ExtraStatus.NONE),
    ("DT007", LoadStatus.ABOVE_MAXIMUM, MinimumReasonState.NOT_NEEDED, ExtraStatus.PENDING),
    ("DT008", LoadStatus.IN_RANGE, MinimumReasonState.NOT_NEEDED, ExtraStatus.NONE),
]


@pytest.mark.parametrize(("identifier", "status", "reason", "extra"), SITUATIONS)
def test_each_demo_teacher_is_in_the_planned_situation(loaded, identifier, status, reason, extra):
    """Eight situations: below the minimum (four reasons), in range, at the maximum, above it."""
    load = load_of(identifier)
    assert load.assessment.status == status
    assert load.minimum_reason == reason
    assert load.extra.status == extra


def test_the_extra_hours_and_the_pending_ones_are_what_the_screens_will_show(loaded):
    """One teacher accepted their excess; the other has not."""
    assert load_of("DT002").extra.accepted_hours == AcceptedExtraHours.objects.get().hours
    assert load_of("DT007").extra.pending_hours > 0


def test_some_lessons_are_still_to_assign(loaded):
    """So the 'por atribuir' marks have something to show."""
    assert TeachingUnit.objects.filter(teacher__isnull=True).exists()
    assert TeachingUnit.objects.filter(teacher__isnull=False).exists()


def test_the_reasons_and_the_other_activities_exist(loaded):
    """Three reasons (two of them reviewed) and two other activities."""
    assert BelowMinimumReason.objects.count() == 3
    assert BelowMinimumReview.objects.count() == 2
    assert OtherActivity.objects.count() == 2


def test_loading_twice_changes_nothing(loaded, settings):
    """Safe to run again: no new records and no new audit entries."""
    models = [Dsd, Offering, TeachingUnit, BelowMinimumReason, BelowMinimumReview, OtherActivity]
    before = {model: model.objects.count() for model in models}
    entries = AuditEntry.objects.count()
    out = StringIO()
    call_command("load_demo_data", stdout=out)
    assert {model: model.objects.count() for model in models} == before
    assert AuditEntry.objects.count() == entries
    assert "nothing (already loaded)" in out.getvalue()


def test_loading_again_does_not_override_what_a_person_did(loaded, settings):
    """If a coordinator took a teacher off a unit, the next load leaves it alone."""
    unit = TeachingUnit.objects.filter(teacher__isnull=False).first()
    TeachingUnit.objects.filter(pk=unit.pk).update(teacher=None)
    call_command("load_demo_data", stdout=StringIO())
    unit.refresh_from_db()
    assert unit.teacher is None
