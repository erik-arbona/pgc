"""Tests for the SII references kept on courses and subjects (T0.3).

Implements: D66 – the course and subject references of the SII are opaque values typed by
the PGC manager; D68 – their uniqueness.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.academic.models import (
    AcademicYear,
    ClassType,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
)
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def faculty():
    """A Faculty."""
    return Faculty.objects.create(name="Faculdade A", code="FA")


@pytest.fixture
def coordination(faculty):
    """A coordination of the Faculty."""
    return Coordination.objects.create(faculty=faculty, name="Coordenação A")


@pytest.fixture
def course(faculty):
    """A course without SII reference."""
    return Course.objects.create(faculty=faculty, name="Curso", level="bachelor")


@pytest.fixture
def plan(course):
    """The 2026 plan of the course."""
    return StudyPlan.objects.create(
        course=course, academic_year=AcademicYear.objects.create(start_year=2026)
    )


def make_subject(plan, coordination, code="S1", **extra):
    """Create a valid subject."""
    data = dict(
        study_plan=plan,
        code=code,
        name=f"Disciplina {code}",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=coordination,
        semester_hours=Decimal("60"),
    )
    data.update(extra)
    return Subject.objects.create(**data)


def manager_of(client, *faculties):
    """Log in a PGC manager assigned to the given Faculties."""
    user = get_user_model().objects.create_user(username="gestor", password="x")
    for faculty in faculties:
        RoleAssignment.objects.create(
            user=user,
            profile=Profile.PGC_MANAGER,
            scope_kind=ScopeKind.FACULTY,
            scope_id=faculty.pk,
        )
    client.force_login(user)
    return user


def course_data(faculty, sii_ref, name="Curso novo", **extra):
    """POST data of the course form."""
    return {"faculty": faculty.pk, "name": name, "level": "bachelor", "sii_ref": sii_ref, **extra}


def subject_data(plan, coordination, sii_ref, code="N1", **extra):
    """POST data of the subject form (4 weekly hours of T x 15 weeks = 60, D60)."""
    return {
        "study_plan": plan.pk,
        "code": code,
        "name": "Nova",
        "ects": "6",
        "curricular_year": 1,
        "semester": 1,
        "coordination": coordination.pk,
        "semester_hours": "60",
        "programme": "",
        "sii_ref": sii_ref,
        f"hours_{ClassType.objects.get(code='T').pk}": "4",
        **extra,
    }


def test_several_courses_may_have_no_sii_reference(faculty):
    """An empty reference is not a value, so any number of courses may leave it empty."""
    Course.objects.create(faculty=faculty, name="Um", level="bachelor")
    Course.objects.create(faculty=faculty, name="Dois", level="bachelor")
    assert Course.objects.filter(sii_ref="").count() == 2


def test_a_sii_reference_identifies_one_course(faculty, course):
    """Two courses cannot share the same SII reference (D68)."""
    course.sii_ref = "CURSO-A"
    course.save()
    with pytest.raises(IntegrityError), transaction.atomic():
        Course.objects.create(faculty=faculty, name="Outro", level="master", sii_ref="CURSO-A")


def test_several_subjects_of_a_plan_may_have_no_sii_reference(plan, coordination):
    """Empty references never collide inside a plan."""
    make_subject(plan, coordination, "S1")
    make_subject(plan, coordination, "S2")
    assert Subject.objects.filter(sii_ref="").count() == 2


def test_a_sii_reference_identifies_one_subject_per_plan(plan, coordination):
    """Inside one plan version a reference points at a single subject (D68)."""
    make_subject(plan, coordination, "S1", sii_ref="DISC-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_subject(plan, coordination, "S2", sii_ref="DISC-1")


def test_the_same_subject_reference_may_repeat_in_another_plan(course, plan, coordination):
    """Each plan version has its own subject rows, so the reference may repeat (D68)."""
    other = StudyPlan.objects.create(
        course=course, academic_year=AcademicYear.objects.create(start_year=2027)
    )
    make_subject(plan, coordination, "S1", sii_ref="DISC-1")
    make_subject(other, coordination, "S1", sii_ref="DISC-1").full_clean()


def test_a_duplicate_course_reference_is_a_form_error(client, faculty, course):
    """The manager sees the error on the form, not a server error."""
    course.sii_ref = "CURSO-A"
    course.save()
    manager_of(client, faculty)
    response = client.post(reverse("academic:course_create"), course_data(faculty, "CURSO-A"))
    assert response.status_code == 200
    assert response.context["form"].errors
    assert Course.objects.count() == 1


def test_a_duplicate_subject_reference_is_a_form_error(client, faculty, plan, coordination):
    """Same for subjects of one plan."""
    make_subject(plan, coordination, "S1", sii_ref="DISC-1")
    manager_of(client, faculty)
    response = client.post(
        reverse("academic:subject_create"), subject_data(plan, coordination, "DISC-1")
    )
    assert response.status_code == 200
    assert response.context["form"].errors
    assert Subject.objects.count() == 1


def test_spaces_around_the_reference_are_removed(client, faculty):
    """Typed with spaces, saved without them."""
    manager_of(client, faculty)
    client.post(reverse("academic:course_create"), course_data(faculty, "  CURSO-A  "))
    assert Course.objects.get().sii_ref == "CURSO-A"


def test_the_reference_is_saved_audited_and_changed_with_a_reason(client, faculty, course):
    """Editing the reference asks for a reason and leaves the old and new values."""
    manager_of(client, faculty)
    url = reverse("academic:course_update", kwargs={"pk": course.pk})
    client.post(url, course_data(faculty, "CURSO-A", name="Curso", reason=""))
    course.refresh_from_db()
    assert course.sii_ref == "" and not AuditEntry.objects.exists()
    client.post(url, course_data(faculty, "CURSO-A", name="Curso", reason="Ligação ao SII"))
    entry = AuditEntry.objects.get()
    assert (entry.old_value["sii_ref"], entry.new_value["sii_ref"]) == ("", "CURSO-A")


def test_a_subject_saved_without_the_field_keeps_working(client, faculty, plan, coordination):
    """The reference is optional in the subject form."""
    manager_of(client, faculty)
    data = subject_data(plan, coordination, "")
    del data["sii_ref"]
    client.post(reverse("academic:subject_create"), data)
    assert Subject.objects.get().sii_ref == ""


def test_the_lists_show_the_references(client, faculty, plan, coordination):
    """Courses and subjects show their SII reference."""
    plan.course.sii_ref = "REF-CURSO"
    plan.course.save()
    make_subject(plan, coordination, "S1", sii_ref="REF-DISC")
    manager_of(client, faculty)
    assert "REF-CURSO" in client.get(reverse("academic:course_list")).content.decode()
    assert "REF-DISC" in client.get(reverse("academic:subject_list")).content.decode()


def test_a_reference_longer_than_the_limit_is_rejected(faculty):
    """The reference has at most 64 characters."""
    course = Course(faculty=faculty, name="X", level="bachelor", sii_ref="A" * 65)
    with pytest.raises(ValidationError):
        course.full_clean()
