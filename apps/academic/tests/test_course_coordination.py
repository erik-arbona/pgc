"""Tests for the coordination responsible for a course (T0.2).

Implements: docs/especificacao/02_perfis_e_dados.md – the coordinator is also the course
director (D10); the responsible coordination belongs to the course's Faculty (D67).
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.urls import reverse

from apps.academic.models import Coordination, Course, Faculty
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def fac_a():
    """Faculty A."""
    return Faculty.objects.create(name="Faculdade A", code="FA")


@pytest.fixture
def fac_b():
    """Faculty B."""
    return Faculty.objects.create(name="Faculdade B", code="FB")


@pytest.fixture
def coord_a(fac_a):
    """A coordination of Faculty A."""
    return Coordination.objects.create(faculty=fac_a, name="Coordenação A")


@pytest.fixture
def coord_b(fac_b):
    """A coordination of Faculty B."""
    return Coordination.objects.create(faculty=fac_b, name="Coordenação B")


def make_course(faculty, name="Curso", **extra):
    """Create a bachelor course."""
    return Course.objects.create(faculty=faculty, name=name, level="bachelor", **extra)


def manager_of(client, *faculties, username="gestor"):
    """Log in a PGC manager assigned to the given Faculties."""
    user = get_user_model().objects.create_user(username=username, password="x")
    for faculty in faculties:
        RoleAssignment.objects.create(
            user=user,
            profile=Profile.PGC_MANAGER,
            scope_kind=ScopeKind.FACULTY,
            scope_id=faculty.pk,
        )
    client.force_login(user)
    return user


def payload(faculty, coordination=None, name="Curso", **extra):
    """POST data of the course form."""
    data = {
        "faculty": faculty.pk,
        "name": name,
        "level": "bachelor",
        "responsible_coordination": coordination.pk if coordination else "",
    }
    data.update(extra)
    return data


def test_a_course_may_have_no_responsible_coordination(fac_a):
    """The link is optional so courses created before it keep working."""
    course = make_course(fac_a)
    course.full_clean()
    assert course.responsible_coordination is None


def test_the_responsible_coordination_must_belong_to_the_course_faculty(fac_a, coord_b):
    """A course of Faculty A cannot be directed by a coordination of Faculty B (D67)."""
    course = Course(faculty=fac_a, name="Curso", level="bachelor", responsible_coordination=coord_b)
    with pytest.raises(ValidationError) as error:
        course.full_clean()
    assert "responsible_coordination" in error.value.message_dict


def test_one_coordination_may_direct_several_courses(fac_a, coord_a):
    """A coordination can be responsible for more than one course."""
    make_course(fac_a, "Curso 1", responsible_coordination=coord_a).full_clean()
    make_course(fac_a, "Curso 2", responsible_coordination=coord_a).full_clean()
    assert coord_a.directed_courses.count() == 2


def test_a_coordination_that_directs_a_course_cannot_be_deleted(fac_a, coord_a):
    """Deleting the coordination would leave the course without a director."""
    make_course(fac_a, responsible_coordination=coord_a)
    with pytest.raises(ProtectedError):
        coord_a.delete()


def test_creating_a_course_with_a_coordination_is_audited(client, fac_a, coord_a):
    """The chosen coordination is saved and appears in the audit entry."""
    manager_of(client, fac_a)
    client.post(reverse("academic:course_create"), payload(fac_a, coord_a))
    course = Course.objects.get()
    assert course.responsible_coordination == coord_a
    entry = AuditEntry.objects.get()
    assert entry.new_value["responsible_coordination"] == coord_a.pk


def test_a_coordination_of_another_faculty_is_refused(client, fac_a, coord_b):
    """The server rejects a coordination from another Faculty and saves nothing."""
    manager_of(client, fac_a)
    response = client.post(reverse("academic:course_create"), payload(fac_a, coord_b))
    assert response.status_code == 200
    assert "responsible_coordination" in response.context["form"].errors
    assert not Course.objects.exists()


def test_a_coordination_outside_the_managers_faculties_is_not_offered(
    client, fac_a, coord_a, coord_b
):
    """The selector lists only coordinations of the manager's own Faculties (D51)."""
    manager_of(client, fac_a)
    response = client.get(reverse("academic:course_create"))
    offered = list(response.context["form"].fields["responsible_coordination"].queryset)
    assert offered == [coord_a]


def test_moving_a_course_to_another_faculty_with_its_coordination_is_refused(
    client, fac_a, fac_b, coord_a
):
    """Changing the Faculty while the old coordination stays selected is an error."""
    course = make_course(fac_a, responsible_coordination=coord_a)
    manager_of(client, fac_a, fac_b)
    response = client.post(
        reverse("academic:course_update", kwargs={"pk": course.pk}),
        payload(fac_b, coord_a, name="Curso", reason="Mudança"),
    )
    assert "responsible_coordination" in response.context["form"].errors
    course.refresh_from_db()
    assert course.faculty_id == fac_a.pk


def test_changing_the_coordination_needs_a_reason_and_is_audited(client, fac_a, coord_a):
    """Updating records the old and the new coordination with the reason."""
    other = Coordination.objects.create(faculty=fac_a, name="Outra")
    course = make_course(fac_a, responsible_coordination=coord_a)
    manager_of(client, fac_a)
    url = reverse("academic:course_update", kwargs={"pk": course.pk})
    client.post(url, payload(fac_a, other, reason=""))
    course.refresh_from_db()
    assert course.responsible_coordination_id == coord_a.pk and not AuditEntry.objects.exists()
    client.post(url, payload(fac_a, other, reason="Nova direção"))
    entry = AuditEntry.objects.get()
    assert entry.old_value["responsible_coordination"] == coord_a.pk
    assert entry.new_value["responsible_coordination"] == other.pk


def test_the_course_list_shows_the_responsible_coordination(client, fac_a, coord_a):
    """The list has a column with the coordination that directs each course."""
    make_course(fac_a, responsible_coordination=coord_a)
    manager_of(client, fac_a)
    page = client.get(reverse("academic:course_list")).content.decode()
    assert "Coordenação A" in page
