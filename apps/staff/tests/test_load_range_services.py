"""Tests for the services that read and write hours ranges.

Implements: docs/especificacao/05_dsd_regras.md – ranges with validity dates; CLAUDE.md rule 7
(audit); D40, D58. A rule already in force is never edited or deleted: it is corrected by adding
a newer one. Future rules can still be changed.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.academic.models import Coordination, Faculty
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.core.permissions import can
from apps.staff.models import Category, LoadRange, Position, Teacher, TeacherPosition
from apps.staff.services import (
    delete_load_range,
    load_range_for,
    load_ranges_for,
    save_load_range,
)

pytestmark = pytest.mark.django_db

PAST = date(2026, 9, 1)  # a rule from this date is in force
TODAY = date(2027, 10, 1)
FUTURE = date(2028, 1, 1)


@pytest.fixture
def actor():
    """The user writing the data."""
    return get_user_model().objects.create_user(username="gestor", password="x")


@pytest.fixture
def doctor():
    """The 'Doutor' category."""
    return Category.objects.get(name="Doutor")


@pytest.fixture
def coordination():
    """A coordination."""
    return Coordination.objects.create(
        faculty=Faculty.objects.create(name="FCT", code="FCT"), name="Informática"
    )


def teacher(coordination, category, kind=Teacher.Type.FULL_TIME, identifier="D1"):
    """Create a teacher."""
    return Teacher.objects.create(
        identifier=identifier,
        name=f"Docente {identifier}",
        coordination=coordination,
        category=category,
        teacher_type=kind,
    )


def category_rule(category, valid_from=PAST, minimum="6", maximum="14"):
    """Build an unsaved category rule."""
    return LoadRange(
        kind=LoadRange.Kind.CATEGORY,
        category=category,
        minimum_hours=Decimal(minimum),
        maximum_hours=Decimal(maximum),
        valid_from=valid_from,
    )


def type_rule(kind=Teacher.Type.HABITUAL_COLLABORATOR, valid_from=PAST, maximum="20"):
    """Build an unsaved teacher-type rule with no minimum."""
    return LoadRange(
        kind=LoadRange.Kind.TEACHER_TYPE,
        teacher_type=kind,
        minimum_hours=None,
        maximum_hours=Decimal(maximum),
        valid_from=valid_from,
    )


def audit(entity="staff.loadrange"):
    """Return the audit entries of an entity in order."""
    return list(AuditEntry.objects.filter(entity=entity).order_by("pk"))


# --- reading ---------------------------------------------------------------------------------


def test_load_range_for_applies_the_lowest_maximum_of_category_and_position(
    coordination, doctor, actor
):
    """A full-time teacher with a position gets the lowest maximum (D11)."""
    chief = Position.objects.create(name="Presidente")
    person = teacher(coordination, doctor)
    TeacherPosition.objects.create(teacher=person, position=chief)
    save_load_range(category_rule(doctor, maximum="14"), actor, "", today=TODAY)
    position_rule = LoadRange(
        kind=LoadRange.Kind.POSITION,
        position=chief,
        minimum_hours=Decimal("4"),
        maximum_hours=Decimal("10"),
        valid_from=PAST,
    )
    save_load_range(position_rule, actor, "", today=TODAY)
    assert load_range_for(person, TODAY).maximum == Decimal("10")


def test_load_range_for_uses_the_type_range_for_a_collaborator(coordination, doctor, actor):
    """The collaborator's range comes from the teacher type, not the category."""
    save_load_range(category_rule(doctor, maximum="14"), actor, "", today=TODAY)
    save_load_range(type_rule(maximum="20"), actor, "", today=TODAY)
    person = teacher(coordination, doctor, Teacher.Type.HABITUAL_COLLABORATOR)
    assert load_range_for(person, TODAY).maximum == Decimal("20")


def test_load_range_for_returns_none_when_nothing_is_defined(coordination, doctor):
    """No rule in force is a gap in the data."""
    assert load_range_for(teacher(coordination, doctor), TODAY) is None


def test_load_range_for_follows_the_date(coordination, doctor, actor):
    """A rule dated in the future applies only from its date."""
    save_load_range(category_rule(doctor, maximum="14"), actor, "", today=TODAY)
    save_load_range(category_rule(doctor, valid_from=FUTURE, maximum="12"), actor, "", today=TODAY)
    person = teacher(coordination, doctor)
    assert load_range_for(person, TODAY).maximum == Decimal("14")
    assert load_range_for(person, FUTURE).maximum == Decimal("12")


def test_load_ranges_for_matches_the_single_version_with_few_queries(
    coordination, doctor, actor, django_assert_max_num_queries
):
    """The bulk version gives the same answers without one query per teacher."""
    chief = Position.objects.create(name="Presidente")
    save_load_range(category_rule(doctor, maximum="14"), actor, "", today=TODAY)
    save_load_range(type_rule(maximum="20"), actor, "", today=TODAY)
    people = [teacher(coordination, doctor, identifier=f"D{i}") for i in range(10)]
    TeacherPosition.objects.create(teacher=people[0], position=chief)
    people.append(teacher(coordination, doctor, Teacher.Type.HABITUAL_COLLABORATOR, "C1"))
    expected = {p.pk: load_range_for(p, TODAY) for p in people}
    with django_assert_max_num_queries(3):
        assert load_ranges_for(people, TODAY) == expected


# --- writing ---------------------------------------------------------------------------------


def test_creating_a_rule_is_audited_and_needs_no_reason(doctor, actor):
    """A new rule leaves a create entry with the actor."""
    rule = category_rule(doctor, valid_from=FUTURE)
    save_load_range(rule, actor, "", today=TODAY)
    entry = audit()[0]
    assert (entry.action, entry.entity_id, entry.actor) == ("create", str(rule.pk), actor)


def test_two_rules_of_one_subject_with_the_same_start_get_a_clear_message(doctor, actor):
    """The overlap is reported in Portuguese before reaching the database."""
    save_load_range(category_rule(doctor), actor, "", today=TODAY)
    with pytest.raises(ValidationError) as error:
        save_load_range(category_rule(doctor, maximum="12"), actor, "", today=TODAY)
    assert "data de início" in str(error.value)
    assert LoadRange.objects.count() == 1


def test_a_future_rule_can_be_updated_with_a_reason(doctor, actor):
    """Changing a rule that has not started is allowed and logged with old and new values."""
    rule = category_rule(doctor, valid_from=FUTURE, maximum="14")
    save_load_range(rule, actor, "", today=TODAY)
    rule.maximum_hours = Decimal("12")
    save_load_range(rule, actor, "Revisão", today=TODAY)
    entry = audit()[-1]
    assert entry.action == "update" and entry.reason == "Revisão"
    assert (
        Decimal(entry.old_value["maximum_hours"]),
        Decimal(entry.new_value["maximum_hours"]),
    ) == (
        Decimal("14"),
        Decimal("12"),
    )


def test_updating_without_a_reason_is_refused(doctor, actor):
    """The reason is required on updates (D40)."""
    rule = category_rule(doctor, valid_from=FUTURE)
    save_load_range(rule, actor, "", today=TODAY)
    rule.maximum_hours = Decimal("12")
    with pytest.raises(ValidationError):
        save_load_range(rule, actor, "", today=TODAY)


def test_a_rule_already_in_force_cannot_be_edited(doctor, actor):
    """Correcting a rule in force means adding a newer one."""
    rule = category_rule(doctor, valid_from=PAST)
    save_load_range(rule, actor, "", today=TODAY)
    rule.maximum_hours = Decimal("12")
    with pytest.raises(ValidationError) as error:
        save_load_range(rule, actor, "Correção", today=TODAY)
    assert "em vigor" in str(error.value)
    assert LoadRange.objects.get().maximum_hours == Decimal("14")


def test_the_rule_starting_today_is_already_in_force(doctor, actor):
    """The start date is inclusive, so a rule starting today is locked."""
    rule = category_rule(doctor, valid_from=TODAY)
    save_load_range(rule, actor, "", today=TODAY)
    rule.maximum_hours = Decimal("12")
    with pytest.raises(ValidationError):
        save_load_range(rule, actor, "Correção", today=TODAY)


def test_the_subject_of_a_rule_cannot_be_changed(doctor, actor):
    """A rule keeps its kind and reference; to change them, delete it and add another."""
    rule = category_rule(doctor, valid_from=FUTURE)
    save_load_range(rule, actor, "", today=TODAY)
    rule.kind = LoadRange.Kind.TEACHER_TYPE
    rule.category = None
    rule.teacher_type = Teacher.Type.COMPETITION
    with pytest.raises(ValidationError):
        save_load_range(rule, actor, "Troca", today=TODAY)


def test_moving_a_future_rule_onto_another_start_date_of_its_subject_is_refused(doctor, actor):
    """The overlap check also applies when editing."""
    save_load_range(category_rule(doctor, valid_from=PAST), actor, "", today=TODAY)
    rule = category_rule(doctor, valid_from=FUTURE)
    save_load_range(rule, actor, "", today=TODAY)
    rule.valid_from = PAST
    with pytest.raises(ValidationError):
        save_load_range(rule, actor, "Mover", today=TODAY)


@pytest.mark.parametrize(
    "overrides",
    [
        {"minimum_hours": Decimal("15"), "maximum_hours": Decimal("14")},
        {"minimum_hours": Decimal("-1")},
        {"maximum_hours": Decimal("-1"), "minimum_hours": Decimal("-1")},
        {"minimum_hours": None},
    ],
)
def test_inconsistent_hours_are_refused_with_a_message(doctor, actor, overrides):
    """Minimum above maximum, negative hours and a missing minimum on a category rule."""
    rule = category_rule(doctor, valid_from=FUTURE)
    for field, value in overrides.items():
        setattr(rule, field, value)
    with pytest.raises(ValidationError):
        save_load_range(rule, actor, "", today=TODAY)
    assert not LoadRange.objects.exists()


def test_a_type_rule_for_full_time_teachers_is_refused(actor):
    """Full-time teachers use category and position ranges only."""
    rule = type_rule(Teacher.Type.FULL_TIME, valid_from=FUTURE)
    with pytest.raises(ValidationError):
        save_load_range(rule, actor, "", today=TODAY)


def test_a_future_rule_can_be_deleted_with_a_reason(doctor, actor):
    """Deleting needs a reason and is logged."""
    rule = category_rule(doctor, valid_from=FUTURE)
    save_load_range(rule, actor, "", today=TODAY)
    with pytest.raises(ValidationError):
        delete_load_range(rule, actor, "", today=TODAY)
    delete_load_range(rule, actor, "Criada por engano", today=TODAY)
    assert not LoadRange.objects.exists()
    assert audit()[-1].action == "delete"


def test_a_rule_in_force_cannot_be_deleted(doctor, actor):
    """Rules that have started are kept so that past DSDs can be recomputed."""
    rule = category_rule(doctor, valid_from=PAST)
    save_load_range(rule, actor, "", today=TODAY)
    with pytest.raises(ValidationError) as error:
        delete_load_range(rule, actor, "Engano", today=TODAY)
    assert "em vigor" in str(error.value)
    assert LoadRange.objects.exists()


@pytest.mark.parametrize("profile", list(Profile))
def test_only_the_pgc_manager_can_edit_load_ranges(profile):
    """The action is registered for the PGC manager alone and needs no scope."""
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
    assert can(user, "load_range.edit") is (profile == Profile.PGC_MANAGER)
