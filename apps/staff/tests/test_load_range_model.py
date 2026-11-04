"""Database tests for the ``LoadRange`` model and its constraints.

Implements: docs/especificacao/05_dsd_regras.md – range of lesson hours with validity dates;
D11, D46, D58. The constraints make a wrong rule impossible to store, whatever the caller.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.staff.load_ranges import RangeRule, RuleKind
from apps.staff.models import Category, LoadRange, Position, Teacher

pytestmark = pytest.mark.django_db

D1 = date(2026, 9, 1)
D2 = date(2027, 9, 1)


@pytest.fixture
def doctor():
    """The 'Doutor' category."""
    return Category.objects.get(name="Doutor")


@pytest.fixture
def chief():
    """A position."""
    return Position.objects.create(name="Presidente de conselho")


def category_rule(category, valid_from=D1, minimum="6", maximum="14"):
    """Create a category rule."""
    return LoadRange.objects.create(
        kind=LoadRange.Kind.CATEGORY,
        category=category,
        minimum_hours=Decimal(minimum),
        maximum_hours=Decimal(maximum),
        valid_from=valid_from,
    )


def type_rule(kind=Teacher.Type.HABITUAL_COLLABORATOR, valid_from=D1, maximum="20", minimum=None):
    """Create a teacher-type rule."""
    return LoadRange.objects.create(
        kind=LoadRange.Kind.TEACHER_TYPE,
        teacher_type=kind,
        minimum_hours=None if minimum is None else Decimal(minimum),
        maximum_hours=Decimal(maximum),
        valid_from=valid_from,
    )


def fails(**kwargs):
    """Assert that creating a rule with these fields violates a database constraint."""
    with pytest.raises(IntegrityError), transaction.atomic():
        LoadRange.objects.create(**kwargs)


def test_the_three_kinds_store_their_own_reference(doctor, chief):
    """Category, position and teacher-type rules each keep only their reference."""
    cat = category_rule(doctor)
    pos = LoadRange.objects.create(
        kind=LoadRange.Kind.POSITION,
        position=chief,
        minimum_hours=Decimal("4"),
        maximum_hours=Decimal("10"),
        valid_from=D1,
    )
    typ = type_rule()
    assert (cat.position, cat.teacher_type) == (None, None)
    assert (pos.category, pos.teacher_type) == (None, None)
    assert (typ.category, typ.position) == (None, None)


def test_a_rule_must_set_exactly_the_reference_of_its_kind(doctor, chief):
    """No reference, the wrong one, or two references are all refused."""
    base = dict(maximum_hours=Decimal("10"), minimum_hours=Decimal("4"), valid_from=D1)
    fails(kind=LoadRange.Kind.CATEGORY, **base)
    fails(kind=LoadRange.Kind.CATEGORY, position=chief, **base)
    fails(kind=LoadRange.Kind.CATEGORY, category=doctor, position=chief, **base)
    fails(kind=LoadRange.Kind.POSITION, category=doctor, **base)
    fails(
        kind=LoadRange.Kind.TEACHER_TYPE,
        category=doctor,
        teacher_type=Teacher.Type.COMPETITION,
        **base,
    )


def test_only_collaborators_and_competition_teachers_have_type_ranges():
    """Full-time teachers use category and position ranges, never a type range (D58)."""
    fails(
        kind=LoadRange.Kind.TEACHER_TYPE,
        teacher_type=Teacher.Type.FULL_TIME,
        maximum_hours=Decimal("20"),
        valid_from=D1,
    )


def test_a_type_range_may_have_no_minimum_but_category_and_position_ranges_need_one(doctor):
    """D46 makes the minimum optional only for the teacher types."""
    assert type_rule(minimum=None).minimum_hours is None
    fails(
        kind=LoadRange.Kind.CATEGORY,
        category=doctor,
        minimum_hours=None,
        maximum_hours=Decimal("14"),
        valid_from=D1,
    )


def test_the_minimum_cannot_be_above_the_maximum(doctor):
    """An inconsistent range is refused."""
    fails(
        kind=LoadRange.Kind.CATEGORY,
        category=doctor,
        minimum_hours=Decimal("15"),
        maximum_hours=Decimal("14"),
        valid_from=D1,
    )


def test_hours_cannot_be_negative(doctor):
    """Neither the maximum nor the minimum can be below zero."""
    fails(
        kind=LoadRange.Kind.CATEGORY,
        category=doctor,
        minimum_hours=Decimal("-1"),
        maximum_hours=Decimal("14"),
        valid_from=D1,
    )
    fails(
        kind=LoadRange.Kind.TEACHER_TYPE,
        teacher_type=Teacher.Type.COMPETITION,
        maximum_hours=Decimal("-1"),
        valid_from=D1,
    )


def test_a_maximum_of_zero_is_allowed(doctor):
    """Zero hours is a valid maximum."""
    assert category_rule(doctor, minimum="0", maximum="0").maximum_hours == 0


def test_two_rules_of_one_subject_cannot_start_on_the_same_day(doctor, chief):
    """Overlaps are impossible: one rule per subject and start date."""
    category_rule(doctor)
    with pytest.raises(IntegrityError), transaction.atomic():
        category_rule(doctor)
    type_rule()
    with pytest.raises(IntegrityError), transaction.atomic():
        type_rule()


def test_the_same_subject_can_have_rules_on_different_dates(doctor):
    """A new rule is a new row with a later start date."""
    category_rule(doctor, valid_from=D1)
    category_rule(doctor, valid_from=D2, maximum="12")
    assert LoadRange.objects.count() == 2


def test_different_subjects_can_share_a_start_date(doctor, chief):
    """Uniqueness is per subject, not global: a category and a position may both start on D1."""
    category_rule(doctor)
    LoadRange.objects.create(
        kind=LoadRange.Kind.POSITION,
        position=chief,
        minimum_hours=Decimal("4"),
        maximum_hours=Decimal("10"),
        valid_from=D1,
    )
    type_rule(Teacher.Type.HABITUAL_COLLABORATOR)
    type_rule(Teacher.Type.COMPETITION)
    assert LoadRange.objects.count() == 4


def test_a_category_or_position_in_use_cannot_be_deleted(doctor, chief):
    """Rules keep their category or position alive."""
    category_rule(doctor)
    LoadRange.objects.create(
        kind=LoadRange.Kind.POSITION,
        position=chief,
        minimum_hours=Decimal("4"),
        maximum_hours=Decimal("10"),
        valid_from=D1,
    )
    for protected in (doctor, chief):
        with pytest.raises(ProtectedError):
            protected.delete()


def test_full_clean_reports_a_broken_rule_as_a_validation_error(doctor):
    """Forms get a message instead of a database error."""
    rule = LoadRange(
        kind=LoadRange.Kind.CATEGORY,
        category=doctor,
        minimum_hours=Decimal("15"),
        maximum_hours=Decimal("14"),
        valid_from=D1,
    )
    with pytest.raises(ValidationError):
        rule.full_clean()


def test_to_rule_converts_each_kind_for_the_domain_function(doctor, chief):
    """The adapter gives the domain a plain rule whose ref matches the kind."""
    cat = category_rule(doctor).to_rule()
    pos = LoadRange.objects.create(
        kind=LoadRange.Kind.POSITION,
        position=chief,
        minimum_hours=Decimal("4"),
        maximum_hours=Decimal("10"),
        valid_from=D1,
    ).to_rule()
    typ = type_rule(Teacher.Type.COMPETITION, maximum="8").to_rule()
    assert isinstance(cat, RangeRule)
    assert (cat.kind, cat.ref) == (RuleKind.CATEGORY, doctor.pk)
    assert (pos.kind, pos.ref) == (RuleKind.POSITION, chief.pk)
    assert (typ.kind, typ.ref, typ.minimum, typ.maximum) == (
        RuleKind.TEACHER_TYPE,
        "competition",
        None,
        Decimal("8"),
    )


def test_rules_are_listed_by_subject_and_newest_first(doctor):
    """The default order puts the latest rule of a subject first."""
    old = category_rule(doctor, valid_from=D1)
    new = category_rule(doctor, valid_from=D2, maximum="12")
    assert list(LoadRange.objects.all()) == [new, old]
