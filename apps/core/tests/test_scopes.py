"""Tests for scope resolution and the guards that keep scope ids from dangling.

Implements: docs/especificacao/07_arquitetura.md – permissions with scope; D38 (a scope is a kind
plus a numeric id, with no foreign key), D51, D56, D62. The scope id of a role is checked against
the record it names, and records that roles point at cannot be deleted.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError

from apps.academic.models import Coordination, Faculty
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.core.scopes import ScopeNotFound, faculty_of_scope
from apps.staff.models import Category, Teacher

pytestmark = pytest.mark.django_db


@pytest.fixture
def faculty():
    """A Faculty."""
    return Faculty.objects.create(name="FCT", code="FCT")


@pytest.fixture
def coordination(faculty):
    """A coordination of the Faculty."""
    return Coordination.objects.create(faculty=faculty, name="Informática")


@pytest.fixture
def teacher(coordination):
    """A teacher of the coordination."""
    return Teacher.objects.create(
        identifier="D1",
        name="Ana",
        coordination=coordination,
        category=Category.objects.get(name="Doutor"),
        teacher_type=Teacher.Type.FULL_TIME,
    )


def test_a_faculty_scope_resolves_to_itself(faculty):
    """The Faculty of a faculty scope is that Faculty."""
    assert faculty_of_scope(ScopeKind.FACULTY, faculty.pk) == faculty.pk


def test_a_coordination_scope_resolves_to_its_faculty(faculty, coordination):
    """The Faculty of a coordination scope is the coordination's Faculty."""
    assert faculty_of_scope(ScopeKind.COORDINATION, coordination.pk) == faculty.pk


def test_a_teacher_scope_resolves_to_the_faculty_of_their_coordination(faculty, teacher):
    """The Faculty of a teacher scope comes from the teacher's coordination."""
    assert faculty_of_scope(ScopeKind.TEACHER, teacher.pk) == faculty.pk


@pytest.mark.parametrize("kind", [ScopeKind.FACULTY, ScopeKind.COORDINATION, ScopeKind.TEACHER])
def test_a_scope_that_does_not_exist_is_refused(kind):
    """An id that names nothing raises instead of resolving to some Faculty."""
    with pytest.raises(ScopeNotFound):
        faculty_of_scope(kind, 987654)


def test_a_scope_kind_without_a_faculty_is_refused():
    """'No scope' has no Faculty, so asking for one is an error."""
    with pytest.raises(ScopeNotFound):
        faculty_of_scope(ScopeKind.NONE, None)


def role(profile, kind, scope_id):
    """Create a role for a new user."""
    user = get_user_model().objects.create_user(username=f"u{RoleAssignment.objects.count()}")
    return RoleAssignment.objects.create(
        user=user, profile=profile, scope_kind=kind, scope_id=scope_id
    )


def test_a_faculty_with_a_role_pointing_at_it_cannot_be_deleted(faculty):
    """Deleting it would leave the role pointing at nothing."""
    role(Profile.PGC_MANAGER, ScopeKind.FACULTY, faculty.pk)
    with pytest.raises(ProtectedError):
        faculty.delete()
    assert Faculty.objects.filter(pk=faculty.pk).exists()


def test_a_coordination_with_a_role_pointing_at_it_cannot_be_deleted(coordination):
    """The same protection for coordinations."""
    role(Profile.COORDINATOR, ScopeKind.COORDINATION, coordination.pk)
    with pytest.raises(ProtectedError):
        coordination.delete()


def test_a_faculty_and_a_coordination_with_the_same_id_do_not_protect_each_other(
    faculty, coordination
):
    """Only a role of the right scope kind protects a record (ids can coincide)."""
    other = Faculty.objects.create(name="Outra", code="OUT")
    role(Profile.COORDINATOR, ScopeKind.COORDINATION, coordination.pk + 1000)
    role(Profile.PGC_MANAGER, ScopeKind.FACULTY, faculty.pk)
    other.delete()  # nothing points at it, even if its id equals a coordination id
    assert not Faculty.objects.filter(pk=other.pk).exists()
