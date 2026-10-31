"""Tests for class groups (turmas) as cohorts that move up each year.

Implements: docs/especificacao/04_modelo_de_dados.md – turmas (one per course and year by
default, several allowed); D48 (plan phase-out) and D49 (turma as a cohort).
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.academic.class_groups import curricular_year_in
from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    Course,
    Faculty,
    StudyPlan,
)
from apps.academic.services import create_class_group
from apps.core.audit import audited_save
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.core.permissions import can


def test_curricular_year_counts_from_the_intake_year():
    """A turma that enters in 2027 is in year 1 in 2027 and year 4 in 2030."""
    assert [curricular_year_in(2027, z) for z in (2027, 2028, 2029, 2030)] == [1, 2, 3, 4]


def test_curricular_year_is_none_before_the_intake_year():
    """Before it enters, the turma has no curricular year."""
    assert curricular_year_in(2027, 2026) is None


def test_curricular_year_is_none_after_the_last_academic_year():
    """A turma that ended in 2028 has no curricular year in 2029 (D49)."""
    assert curricular_year_in(2027, 2028, last_year=2028) == 2
    assert curricular_year_in(2027, 2029, last_year=2028) is None


pytestmark_db = pytest.mark.django_db


@pytest.fixture
def course(db):
    """A bachelor course."""
    faculty = Faculty.objects.create(name="FCT", code="FCT")
    return Course.objects.create(faculty=faculty, name="Eng", level="bachelor")


def year(start):
    """Get or create an academic year."""
    return AcademicYear.objects.get_or_create(start_year=start)[0]


def plan(course, start):
    """Create the study plan of a course that starts in the given year."""
    return StudyPlan.objects.create(course=course, academic_year=year(start))


@pytest.mark.django_db
def test_new_turma_gets_the_plan_in_force_for_the_first_year(course):
    """Intake 2027 uses the plan that starts in 2027; intake 2026 uses the older one."""
    old, new = plan(course, 2020), plan(course, 2027)
    assert create_class_group(course, year(2027)).study_plan == new
    assert create_class_group(course, year(2026)).study_plan == old


@pytest.mark.django_db
def test_creating_a_turma_without_any_plan_in_force_fails(course):
    """No plan has reached the first year yet: the turma cannot be created."""
    plan(course, 2030)
    with pytest.raises(ValidationError):
        create_class_group(course, year(2027))


@pytest.mark.django_db
def test_a_turma_keeps_its_plan_when_a_new_plan_appears(course):
    """A turma never changes plan (D48)."""
    old = plan(course, 2020)
    group = create_class_group(course, year(2026))
    plan(course, 2027)
    group.refresh_from_db()
    assert group.study_plan == old
    group.study_plan = StudyPlan.objects.exclude(pk=old.pk).get()
    with pytest.raises(ValidationError):
        group.save()


@pytest.mark.django_db
def test_study_plan_must_belong_to_the_same_course(course):
    """The fixed plan has to be a plan of the turma's course."""
    other = Course.objects.create(faculty=course.faculty, name="Outro", level="bachelor")
    with pytest.raises(ValidationError):
        ClassGroup.objects.create(
            course=course, intake_year=year(2027), study_plan=plan(other, 2020)
        )


@pytest.mark.django_db
def test_several_turmas_in_the_same_year_need_different_labels(course):
    """1.º A and 1.º B coexist; the same label twice, or two without label, do not."""
    plan(course, 2020)
    create_class_group(course, year(2027), label="A")
    create_class_group(course, year(2027), label="B")
    with pytest.raises(IntegrityError), transaction.atomic():
        create_class_group(course, year(2027), label="A")


@pytest.mark.django_db
def test_two_unlabeled_turmas_in_the_same_year_are_rejected(course):
    """With no label the default single turma is unique per course and intake year."""
    plan(course, 2020)
    create_class_group(course, year(2027))
    with pytest.raises(IntegrityError), transaction.atomic():
        create_class_group(course, year(2027))


@pytest.mark.django_db
def test_a_course_may_skip_an_intake_year(course):
    """Not opening a course in 2028 simply leaves that year without a turma."""
    plan(course, 2020)
    create_class_group(course, year(2027))
    create_class_group(course, year(2029))
    assert set(ClassGroup.objects.values_list("intake_year__start_year", flat=True)) == {2027, 2029}


@pytest.mark.django_db
def test_last_academic_year_cannot_precede_the_intake_year(course):
    """A turma cannot end before it starts."""
    plan(course, 2020)
    with pytest.raises(ValidationError):
        create_class_group(course, year(2027), last_year=year(2026))


@pytest.mark.django_db
def test_model_curricular_year_follows_the_last_academic_year(course):
    """The model reports the year while active and None once it has ended."""
    plan(course, 2020)
    group = create_class_group(course, year(2027), last_year=year(2028))
    assert group.curricular_year_in(2028) == 2
    assert group.curricular_year_in(2029) is None


@pytest.mark.django_db
def test_records_in_use_cannot_be_deleted(course):
    """A course, plan or academic year with a turma is protected."""
    study_plan = plan(course, 2020)
    group = create_class_group(course, year(2027))
    for protected in (course, study_plan, group.intake_year):
        with pytest.raises(ProtectedError):
            protected.delete()


@pytest.mark.django_db
def test_creating_a_turma_through_audited_save_is_audited(course):
    """Turma changes leave an audit entry."""
    study_plan = plan(course, 2020)
    actor = get_user_model().objects.create_user(username="gestor", password="x")
    group = ClassGroup(course=course, intake_year=year(2027), study_plan=study_plan)
    audited_save(group, actor)
    assert AuditEntry.objects.filter(entity="academic.classgroup", entity_id=str(group.pk)).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("profile", list(Profile))
def test_only_the_pgc_manager_can_edit_class_groups(profile):
    """Turmas are created by the PGC manager (D49, to confirm)."""
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
    assert can(user, "class_group.edit") is (profile == Profile.PGC_MANAGER)
