"""Database tests for cross-course subject groups.

Implements: docs/especificacao/04_modelo_de_dados.md – cross-course subjects; D22, D47.
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
    CrossCourseSubject,
    CrossCourseSubjectCourse,
    CrossCourseSubjectMember,
    Faculty,
    StudyPlan,
    Subject,
    SubjectClassLoad,
)
from apps.academic.services import facts_for
from apps.core.audit import audited_save
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.core.permissions import can

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    """Two courses with one introductory subject each, plus a third course."""
    faculty = Faculty.objects.create(name="FCT", code="FCT")
    coordination = Coordination.objects.create(faculty=faculty, name="Informática")
    year = AcademicYear.objects.create(start_year=2026)
    subjects = {}
    courses = {}
    for key in ("EIC", "TM", "ENG"):
        course = Course.objects.create(faculty=faculty, name=key, level="bachelor")
        plan = StudyPlan.objects.create(course=course, academic_year=year)
        subjects[key] = Subject.objects.create(
            study_plan=plan,
            code="P1",
            name="Introdução à Programação",
            ects=Decimal("6"),
            curricular_year=1,
            semester=1,
            coordination=coordination,
            semester_hours=Decimal("75"),
        )
        courses[key] = course
    return subjects, courses


def test_a_subject_cannot_belong_to_two_groups(world):
    """Membership is exclusive: one group per subject."""
    subjects, _ = world
    a = CrossCourseSubject.objects.create(name="Programação")
    b = CrossCourseSubject.objects.create(name="Outra")
    CrossCourseSubjectMember.objects.create(cross_course_subject=a, subject=subjects["EIC"])
    with pytest.raises(IntegrityError), transaction.atomic():
        CrossCourseSubjectMember.objects.create(cross_course_subject=b, subject=subjects["EIC"])


def test_an_allowed_course_cannot_be_listed_twice(world):
    """A course appears once in the allowed courses of a group."""
    _, courses = world
    group = CrossCourseSubject.objects.create(name="Programação")
    CrossCourseSubjectCourse.objects.create(cross_course_subject=group, course=courses["EIC"])
    with pytest.raises(IntegrityError), transaction.atomic():
        CrossCourseSubjectCourse.objects.create(cross_course_subject=group, course=courses["EIC"])


def test_declared_in_two_courses_and_refused_in_a_third(world):
    """The group lists EIC and TM as allowed; ENG is a member course that is not allowed."""
    subjects, courses = world
    group = CrossCourseSubject.objects.create(name="Programação")
    for key in ("EIC", "TM", "ENG"):
        CrossCourseSubjectMember.objects.create(cross_course_subject=group, subject=subjects[key])
    for key in ("EIC", "TM"):
        CrossCourseSubjectCourse.objects.create(cross_course_subject=group, course=courses[key])
    allowed = set(group.allowed_courses.values_list("course__name", flat=True))
    assert allowed == {"EIC", "TM"}


def test_a_subject_in_a_group_cannot_be_deleted(world):
    """Members are protected: the subject must leave the group first."""
    subjects, _ = world
    group = CrossCourseSubject.objects.create(name="Programação")
    CrossCourseSubjectMember.objects.create(cross_course_subject=group, subject=subjects["EIC"])
    with pytest.raises(ProtectedError):
        subjects["EIC"].delete()


def test_adding_a_member_through_audited_save_is_audited(world):
    """Group changes leave an audit entry."""
    subjects, _ = world
    actor = get_user_model().objects.create_user(username="gestor", password="x")
    group = CrossCourseSubject(name="Programação")
    audited_save(group, actor)
    member = CrossCourseSubjectMember(cross_course_subject=group, subject=subjects["EIC"])
    audited_save(member, actor)
    assert AuditEntry.objects.filter(
        entity="academic.crosscoursesubjectmember", entity_id=str(member.pk)
    ).exists()


def test_facts_for_collects_weekly_hours_by_class_type(world):
    """The adapter turns a subject into plain facts for the domain functions."""
    subjects, courses = world
    SubjectClassLoad.objects.create(
        subject=subjects["EIC"], class_type=ClassType.objects.get(code="T"), weekly_hours=3
    )
    result = facts_for(subjects["EIC"])
    assert result.course_id == courses["EIC"].pk
    assert result.weekly_hours == {"T": Decimal("3")}
    assert result.semester_hours == Decimal("75")


def test_subject_programme_is_optional(world):
    """The programme text may stay empty."""
    assert world[0]["EIC"].programme == ""


@pytest.mark.parametrize("profile", list(Profile))
def test_only_the_pgc_manager_can_edit_cross_course_subjects(profile):
    """Declaring cross-course subjects is the PGC manager's job (D06, D22)."""
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
    assert can(user, "cross_course_subject.edit") is (profile == Profile.PGC_MANAGER)
