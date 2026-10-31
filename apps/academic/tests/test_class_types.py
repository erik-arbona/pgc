"""Tests for configurable class types.

Implements: docs/especificacao/02_perfis_e_dados.md – class types (T, TP, P, L and others)
configured by the PGC manager. See D45.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.academic.models import (
    AcademicYear,
    ClassType,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
    SubjectClassLoad,
)
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.core.permissions import can

pytestmark = pytest.mark.django_db


def test_initial_class_types_are_loaded_by_the_migration():
    """T, TP, P, L and 'other' exist after migrating, in this display order."""
    assert list(ClassType.objects.values_list("code", flat=True)) == ["T", "TP", "P", "L", "OUT"]


def test_new_class_types_are_active_by_default():
    """A type created by the manager can be used straight away."""
    assert ClassType.objects.create(code="S", name="Seminário", position=10).is_active


def test_class_types_are_ordered_by_position_then_code():
    """The display order is configurable through ``position``."""
    ClassType.objects.create(code="AAA", name="First", position=0)
    assert ClassType.objects.first().code == "AAA"


@pytest.fixture
def subject():
    """A subject to attach loads to."""
    faculty = Faculty.objects.create(name="FCT", code="FCT")
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="Eng", level="bachelor"),
        academic_year=AcademicYear.objects.create(start_year=2026),
    )
    return Subject.objects.create(
        study_plan=plan,
        code="INF101",
        name="Introdução à Programação",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=Coordination.objects.create(faculty=faculty, name="Informática"),
        semester_hours=Decimal("75"),
    )


def test_an_inactive_class_type_cannot_be_given_to_a_subject(subject):
    """Deactivated types are not offered for new loads."""
    inactive = ClassType.objects.create(code="X", name="Old", is_active=False)
    with pytest.raises(ValidationError):
        SubjectClassLoad.objects.create(
            subject=subject, class_type=inactive, weekly_hours=Decimal("1")
        )


def test_an_existing_load_keeps_a_class_type_deactivated_later(subject):
    """Deactivating a type does not break the subjects that already use it."""
    theory = ClassType.objects.get(code="T")
    load = SubjectClassLoad.objects.create(
        subject=subject, class_type=theory, weekly_hours=Decimal("3")
    )
    theory.is_active = False
    theory.save()
    load.weekly_hours = Decimal("2")
    load.save()
    assert subject.weekly_hours_total == Decimal("2")


def test_weekly_load_example_three_theory_and_two_practice(subject):
    """5 weekly hours split as 3 T and 2 P (the manager's example)."""
    for code, hours in (("T", "3"), ("P", "2")):
        SubjectClassLoad.objects.create(
            subject=subject,
            class_type=ClassType.objects.get(code=code),
            weekly_hours=Decimal(hours),
        )
    assert subject.weekly_hours_total == Decimal("5")


@pytest.mark.parametrize("profile", list(Profile))
def test_only_the_pgc_manager_can_edit_class_types(profile):
    """Class types are configured by the PGC manager only."""
    user = get_user_model().objects.create_user(username="u", password="x")
    kind = {
        Profile.PGC_MANAGER: ScopeKind.FACULTY,
        Profile.COORDINATOR: ScopeKind.COORDINATION,
        Profile.EXECUTIVE_BOARD: ScopeKind.FACULTY,
        Profile.TEACHER: ScopeKind.TEACHER,
    }.get(profile, ScopeKind.NONE)
    RoleAssignment.objects.create(
        user=user, profile=profile, scope_kind=kind, scope_id=None if kind == "none" else 1
    )
    assert can(user, "class_type.edit") is (profile == Profile.PGC_MANAGER)
