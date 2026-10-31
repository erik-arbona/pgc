"""Tests for study plans, subjects and weekly load per class type.

Implements: docs/especificacao/04_modelo_de_dados.md – study plan, subject;
docs/especificacao/02_perfis_e_dados.md – weekly load split by class type. See D44.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

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
from apps.core.audit import audited_save
from apps.core.models import AuditEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def faculty():
    """A faculty."""
    return Faculty.objects.create(name="Faculdade de Ciências e Tecnologia", code="FCT")


@pytest.fixture
def coordination(faculty):
    """A coordination of the faculty."""
    return Coordination.objects.create(faculty=faculty, name="Informática")


@pytest.fixture
def course(faculty):
    """A bachelor course."""
    return Course.objects.create(faculty=faculty, name="Eng. Informática", level="bachelor")


@pytest.fixture
def year():
    """Academic year 2026/2027."""
    return AcademicYear.objects.create(start_year=2026)


@pytest.fixture
def plan(course, year):
    """The study plan of the course that starts in 2026."""
    return StudyPlan.objects.create(course=course, academic_year=year)


def make_subject(plan, coordination, **overrides):
    """Create a valid subject, overriding any field."""
    data = dict(
        study_plan=plan,
        code="INF101",
        name="Programação I",
        ects=Decimal("6.00"),
        curricular_year=1,
        semester=1,
        coordination=coordination,
        semester_hours=Decimal("60.00"),
    )
    data.update(overrides)
    return Subject.objects.create(**data)


@pytest.fixture
def theory():
    """The theoretical class type."""
    return ClassType.objects.get(code="T")


@pytest.fixture
def practice():
    """The practical class type."""
    return ClassType.objects.get(code="P")


def test_a_course_has_one_study_plan_per_academic_year(course, year):
    """Plans are versioned by the academic year in which they start."""
    StudyPlan.objects.create(course=course, academic_year=year)
    with pytest.raises(IntegrityError), transaction.atomic():
        StudyPlan.objects.create(course=course, academic_year=year)


def test_a_course_may_have_plans_in_different_academic_years(course, year):
    """A newer plan version for the same course is allowed."""
    StudyPlan.objects.create(course=course, academic_year=year)
    StudyPlan.objects.create(
        course=course, academic_year=AcademicYear.objects.create(start_year=2027)
    )
    assert StudyPlan.objects.count() == 2


def test_subject_code_is_unique_within_a_study_plan(plan, coordination):
    """Two subjects of one plan cannot share a code."""
    make_subject(plan, coordination)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_subject(plan, coordination, name="Outra")


def test_same_code_is_allowed_in_different_plans(plan, course, coordination):
    """Plans of two years may both contain the same subject code."""
    other = StudyPlan.objects.create(
        course=course, academic_year=AcademicYear.objects.create(start_year=2027)
    )
    make_subject(plan, coordination)
    make_subject(other, coordination)
    assert Subject.objects.count() == 2


@pytest.mark.parametrize("semester", [0, 3])
def test_semester_must_be_first_or_second(plan, coordination, semester):
    """Only semesters 1 and 2 exist."""
    with pytest.raises(IntegrityError), transaction.atomic():
        make_subject(plan, coordination, semester=semester)


@pytest.mark.parametrize("ects", [Decimal("0"), Decimal("-1")])
def test_ects_must_be_positive(plan, coordination, ects):
    """A subject carries at least some ECTS."""
    with pytest.raises(IntegrityError), transaction.atomic():
        make_subject(plan, coordination, ects=ects)


def test_curricular_year_must_be_at_least_one(plan, coordination):
    """Curricular years start at 1."""
    with pytest.raises(IntegrityError), transaction.atomic():
        make_subject(plan, coordination, curricular_year=0)


def test_semester_hours_cannot_be_negative(plan, coordination):
    """The semester load is zero or more hours."""
    with pytest.raises(IntegrityError), transaction.atomic():
        make_subject(plan, coordination, semester_hours=Decimal("-1"))


def test_a_subject_may_belong_to_a_coordination_of_another_faculty(plan, other_coordination):
    """The specification sets no same-faculty rule between course and coordination."""
    assert make_subject(plan, other_coordination).pk


@pytest.fixture
def other_coordination():
    """A coordination in a different faculty."""
    other = Faculty.objects.create(name="Faculdade de Educação", code="FEd")
    return Coordination.objects.create(faculty=other, name="Educação")


def test_class_type_appears_once_per_subject(plan, coordination, theory):
    """A subject has at most one weekly load row per class type."""
    subject = make_subject(plan, coordination)
    SubjectClassLoad.objects.create(subject=subject, class_type=theory, weekly_hours=Decimal("2"))
    with pytest.raises(IntegrityError), transaction.atomic():
        SubjectClassLoad.objects.create(
            subject=subject, class_type=theory, weekly_hours=Decimal("1")
        )


def test_weekly_hours_must_be_positive(plan, coordination, theory):
    """A load row with zero hours is meaningless."""
    subject = make_subject(plan, coordination)
    with pytest.raises(IntegrityError), transaction.atomic():
        SubjectClassLoad.objects.create(
            subject=subject, class_type=theory, weekly_hours=Decimal("0")
        )


def test_weekly_total_is_sum_of_class_type_hours(plan, coordination, theory, practice):
    """The weekly total adds the hours of every class type."""
    subject = make_subject(plan, coordination)
    SubjectClassLoad.objects.create(subject=subject, class_type=theory, weekly_hours=Decimal("2"))
    SubjectClassLoad.objects.create(
        subject=subject, class_type=practice, weekly_hours=Decimal("1.5")
    )
    assert subject.weekly_hours_total == Decimal("3.5")


def test_weekly_total_is_zero_without_class_loads(plan, coordination):
    """A subject without load rows has no weekly hours."""
    assert make_subject(plan, coordination).weekly_hours_total == Decimal("0")


def test_class_type_code_is_unique():
    """Two class types cannot share a code."""
    with pytest.raises(IntegrityError), transaction.atomic():
        ClassType.objects.create(code="T", name="Outra")


def test_records_in_use_cannot_be_deleted(plan, course, coordination, theory):
    """Courses, plans, coordinations and class types in use are protected."""
    subject = make_subject(plan, coordination)
    SubjectClassLoad.objects.create(subject=subject, class_type=theory, weekly_hours=Decimal("2"))
    for protected in (course, plan, coordination, subject, theory):
        with pytest.raises(ProtectedError):
            protected.delete()


def test_audited_save_keeps_decimal_hours_in_the_audit_entry(plan, coordination):
    """Decimal values survive the JSON snapshot of the audit log."""
    actor = get_user_model().objects.create_user(username="gestor", password="x")
    subject = Subject(
        study_plan=plan,
        code="INF102",
        name="Programação II",
        ects=Decimal("6.00"),
        curricular_year=1,
        semester=2,
        coordination=coordination,
        semester_hours=Decimal("52.50"),
    )
    audited_save(subject, actor)
    entry = AuditEntry.objects.get(entity="academic.subject", entity_id=str(subject.pk))
    assert Decimal(entry.new_value["semester_hours"]) == Decimal("52.50")
