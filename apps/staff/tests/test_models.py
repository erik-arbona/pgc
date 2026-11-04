"""Tests for teachers, categories, positions and position assignments.

Implements: docs/especificacao/04_modelo_de_dados.md – teacher; 02_perfis_e_dados.md – teachers,
categories and positions entered by the PGC manager; D46 (three teacher types, positions only
for full-time teachers), D56.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.academic.models import Coordination, Faculty
from apps.core.audit import audited_save
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.core.permissions import can
from apps.staff.models import Category, Position, Teacher, TeacherPosition

pytestmark = pytest.mark.django_db


@pytest.fixture
def coordination():
    """A coordination in a Faculty."""
    faculty = Faculty.objects.create(name="FCT", code="FCT")
    return Coordination.objects.create(faculty=faculty, name="Informática")


@pytest.fixture
def doctor():
    """The 'Doutor' category loaded by the migration."""
    return Category.objects.get(name="Doutor")


def make_teacher(coordination, category, identifier="D001", **overrides):
    """Create a full-time teacher, overriding any field."""
    data = dict(
        identifier=identifier,
        name="Ana Silva",
        coordination=coordination,
        category=category,
        teacher_type=Teacher.Type.FULL_TIME,
    )
    data.update(overrides)
    return Teacher.objects.create(**data)


@pytest.fixture
def adviser():
    """A position (cargo)."""
    return Position.objects.create(name="Assessor")


def test_the_three_scientific_degrees_are_loaded_by_the_migration():
    """Licenciado, Mestre and Doutor exist after migrating, in this order."""
    assert list(Category.objects.values_list("name", flat=True)) == [
        "Licenciado",
        "Mestre",
        "Doutor",
    ]


def test_no_positions_are_loaded_by_default():
    """The specification only gives examples of positions, so none are preloaded."""
    assert not Position.objects.exists()


def test_the_three_teacher_types_of_d46_exist():
    """Full-time, habitual collaborator and competition teacher."""
    assert {t.value for t in Teacher.Type} == {
        "full_time",
        "habitual_collaborator",
        "competition",
    }


def test_the_identifier_is_unique_ignoring_case(coordination, doctor):
    """A teacher is a single person across the University (07_arquitetura)."""
    make_teacher(coordination, doctor, "abc1")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_teacher(coordination, doctor, "ABC1")
    make_teacher(coordination, doctor, "ABC2")
    assert Teacher.objects.count() == 2


def test_category_name_and_position_name_are_unique():
    """Catalogue entries are not duplicated."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(code="DOU2", name="Doutor")
    Position.objects.create(name="Assessor")
    with pytest.raises(IntegrityError), transaction.atomic():
        Position.objects.create(name="Assessor")


def test_a_teacher_cannot_hold_the_same_position_twice(coordination, doctor, adviser):
    """One assignment per teacher and position."""
    teacher = make_teacher(coordination, doctor)
    TeacherPosition.objects.create(teacher=teacher, position=adviser)
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherPosition.objects.create(teacher=teacher, position=adviser)


@pytest.mark.parametrize("kind", ["habitual_collaborator", "competition"])
def test_only_full_time_teachers_can_hold_positions(coordination, doctor, adviser, kind):
    """Collaborators and competition teachers have no positions (D56)."""
    teacher = make_teacher(coordination, doctor, teacher_type=kind)
    with pytest.raises(ValidationError):
        TeacherPosition.objects.create(teacher=teacher, position=adviser)
    assert not TeacherPosition.objects.exists()


def test_a_teacher_with_positions_cannot_stop_being_full_time(coordination, doctor, adviser):
    """The positions have to be removed first."""
    teacher = make_teacher(coordination, doctor)
    TeacherPosition.objects.create(teacher=teacher, position=adviser)
    teacher.teacher_type = Teacher.Type.COMPETITION
    with pytest.raises(ValidationError):
        teacher.save()
    teacher.refresh_from_db()
    assert teacher.teacher_type == Teacher.Type.FULL_TIME


def test_a_teacher_without_positions_may_change_type(coordination, doctor):
    """Without positions the type can change."""
    teacher = make_teacher(coordination, doctor)
    teacher.teacher_type = Teacher.Type.HABITUAL_COLLABORATOR
    teacher.save()
    teacher.refresh_from_db()
    assert teacher.teacher_type == Teacher.Type.HABITUAL_COLLABORATOR


def test_an_inactive_position_cannot_be_newly_assigned(coordination, doctor):
    """Deactivated positions are not given to anyone new."""
    teacher = make_teacher(coordination, doctor)
    old = Position.objects.create(name="Antigo", is_active=False)
    with pytest.raises(ValidationError):
        TeacherPosition.objects.create(teacher=teacher, position=old)


def test_catalogue_entries_in_use_cannot_be_deleted(coordination, doctor, adviser):
    """Coordination, category and position are protected while a teacher uses them."""
    teacher = make_teacher(coordination, doctor)
    TeacherPosition.objects.create(teacher=teacher, position=adviser)
    for protected in (coordination, doctor, adviser):
        with pytest.raises(ProtectedError):
            protected.delete()


def test_deleting_a_teacher_removes_the_position_assignments(coordination, doctor, adviser):
    """The join rows go with the teacher (the service audits them first)."""
    teacher = make_teacher(coordination, doctor)
    TeacherPosition.objects.create(teacher=teacher, position=adviser)
    teacher.delete()
    assert not TeacherPosition.objects.exists()


def test_a_teacher_with_a_teacher_role_cannot_be_deleted(coordination, doctor):
    """A role of kind 'teacher' points at the teacher (D38): deletion is refused."""
    teacher = make_teacher(coordination, doctor)
    user = get_user_model().objects.create_user(username="ana", password="x")
    RoleAssignment.objects.create(
        user=user, profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER, scope_id=teacher.pk
    )
    with pytest.raises(ProtectedError):
        teacher.delete()
    assert Teacher.objects.filter(pk=teacher.pk).exists()


def test_a_teacher_without_a_role_can_be_deleted(coordination, doctor):
    """Without any role pointing at it the teacher is deleted."""
    teacher = make_teacher(coordination, doctor)
    teacher.delete()
    assert not Teacher.objects.exists()


def test_audited_save_logs_a_teacher(coordination, doctor):
    """A teacher saved through the audit function leaves a create entry."""
    actor = get_user_model().objects.create_user(username="gestor", password="x")
    teacher = Teacher(
        identifier="D009",
        name="Rui Costa",
        coordination=coordination,
        category=doctor,
        teacher_type=Teacher.Type.COMPETITION,
    )
    audited_save(teacher, actor)
    entry = AuditEntry.objects.get(entity="staff.teacher")
    assert entry.action == "create" and entry.new_value["identifier"] == "D009"


@pytest.mark.parametrize("profile", list(Profile))
def test_only_the_pgc_manager_has_the_staff_actions(profile):
    """teacher.edit (scoped), position.edit and category.edit belong to the PGC manager."""
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
    expected = profile == Profile.PGC_MANAGER
    assert can(user, "teacher.edit", ScopeKind.FACULTY, 1) is expected
    assert can(user, "position.edit") is expected
    assert can(user, "category.edit") is expected


def test_teacher_edit_is_scoped_and_fails_closed_without_a_scope():
    """Checking teacher.edit without a Faculty is a programming error, never 'any scope'."""
    user = get_user_model().objects.create_user(username="m", password="x")
    with pytest.raises(ImproperlyConfigured):
        can(user, "teacher.edit")
