"""Tests for faculties, coordinations, courses and academic years.

Implements: docs/especificacao/04_modelo_de_dados.md – Faculty, Coordination, Course;
docs/glossario.md – AcademicYear.
"""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.academic.models import AcademicYear, Coordination, Course, Faculty

pytestmark = pytest.mark.django_db


@pytest.fixture
def fct(db):
    """A faculty."""
    return Faculty.objects.create(name="Faculdade de Ciências e Tecnologia", code="FCT")


@pytest.fixture
def other_faculty(db):
    """A second faculty."""
    return Faculty.objects.create(name="Faculdade de Educação", code="FEd")


def test_faculty_code_is_unique():
    """Two faculties cannot share the same code."""
    Faculty.objects.create(name="A", code="FA")
    with pytest.raises(IntegrityError), transaction.atomic():
        Faculty.objects.create(name="B", code="FA")


def test_coordination_name_is_unique_within_a_faculty_but_not_across_faculties(fct, other_faculty):
    """The same coordination name may exist in two faculties, never twice in one."""
    Coordination.objects.create(faculty=fct, name="Informática")
    Coordination.objects.create(faculty=other_faculty, name="Informática")
    with pytest.raises(IntegrityError), transaction.atomic():
        Coordination.objects.create(faculty=fct, name="Informática")


def test_a_course_with_the_same_name_may_exist_at_different_levels(fct):
    """A bachelor and a master with the same name are different courses."""
    Course.objects.create(faculty=fct, name="Engenharia Informática", level=Course.Level.BACHELOR)
    Course.objects.create(faculty=fct, name="Engenharia Informática", level=Course.Level.MASTER)
    assert Course.objects.count() == 2


def test_the_same_course_cannot_be_created_twice_in_a_faculty(fct):
    """Faculty, name and level together identify a course."""
    kwargs = dict(faculty=fct, name="Engenharia Informática", level=Course.Level.BACHELOR)
    Course.objects.create(**kwargs)
    with pytest.raises(IntegrityError), transaction.atomic():
        Course.objects.create(**kwargs)


def test_course_levels_cover_bachelor_master_and_doctorate():
    """Courses range from bachelor ('licenciatura') to doctorate."""
    assert {level.value for level in Course.Level} == {"bachelor", "master", "doctorate"}


def test_a_faculty_with_coordinations_or_courses_cannot_be_deleted(fct):
    """Deleting a faculty never silently removes its coordinations and courses."""
    Coordination.objects.create(faculty=fct, name="Informática")
    with pytest.raises(ProtectedError):
        fct.delete()

    Coordination.objects.all().delete()
    Course.objects.create(faculty=fct, name="Eng", level=Course.Level.BACHELOR)
    with pytest.raises(ProtectedError):
        fct.delete()


def test_academic_year_label_is_derived_from_the_start_year():
    """Academic year 2026 is shown as 2026/2027."""
    assert AcademicYear(start_year=2026).label == "2026/2027"
    assert str(AcademicYear(start_year=2026)) == "2026/2027"


def test_academic_year_start_year_is_unique():
    """There is one academic year per start year."""
    AcademicYear.objects.create(start_year=2026)
    with pytest.raises(IntegrityError), transaction.atomic():
        AcademicYear.objects.create(start_year=2026)
