"""View tests for the study plan and subject screens, limited to the manager's Faculties.

Implements: docs/especificacao/03_requisitos_funcionais.md – block 1 (study plans and
subjects entered by the PGC manager); D39, D40, D44, D50, D51.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

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
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind

pytestmark = pytest.mark.django_db

SCREENS = ["studyplan", "subject"]
MODELS = {"studyplan": StudyPlan, "subject": Subject}
SCOPE_FIELD = {"studyplan": "course", "subject": "study_plan"}


class Setup:
    """A Faculty with a course, an academic year, a plan and a coordination."""

    def __init__(self, code, year=2026):
        self.faculty = Faculty.objects.create(name=f"Faculdade {code}", code=code)
        self.course = Course.objects.create(
            faculty=self.faculty, name=f"Curso {code}", level="master"
        )
        self.year = AcademicYear.objects.get_or_create(start_year=year)[0]
        self.plan = StudyPlan.objects.create(course=self.course, academic_year=self.year)
        self.coordination = Coordination.objects.create(faculty=self.faculty, name=f"Coord {code}")

    def subject(self, code="S1", **overrides):
        """Create a subject in this Faculty's plan."""
        data = dict(
            study_plan=self.plan,
            code=code,
            name=f"Disciplina {code}",
            ects=Decimal("6"),
            curricular_year=1,
            semester=1,
            coordination=self.coordination,
            semester_hours=Decimal("60"),
        )
        data.update(overrides)
        return Subject.objects.create(**data)

    def post_data(self, screen, code="N1", name="Nova"):
        """Valid POST data for the screen."""
        if screen == "studyplan":
            other_year = AcademicYear.objects.get_or_create(start_year=2030)[0]
            return {"course": self.course.pk, "academic_year": other_year.pk}
        return {
            "study_plan": self.plan.pk,
            "code": code,
            "name": name,
            "ects": "6",
            "curricular_year": 1,
            "semester": 1,
            "coordination": self.coordination.pk,
            "semester_hours": "60",
            "programme": "",
            # Every subject has weekly hours; 4 h x 15 weeks = the 60 semester hours (D60).
            f"hours_{ClassType.objects.get(code='T').pk}": "4",
        }

    def item(self, screen):
        """An existing item of the screen's model."""
        return self.plan if screen == "studyplan" else self.subject()


@pytest.fixture
def a():
    """Faculty A and its data."""
    return Setup("A")


@pytest.fixture
def b():
    """Faculty B and its data."""
    return Setup("B", year=2027)


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


@pytest.mark.parametrize("screen", SCREENS)
def test_anonymous_visitors_are_redirected_to_login(client, screen):
    """The lists require a session."""
    response = client.get(reverse(f"academic:{screen}_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, a, screen, profile):
    """Only the PGC manager reaches these screens."""
    client.force_login(make_user(profile))
    before = MODELS[screen].objects.count()
    for name in ("list", "create"):
        url = reverse(f"academic:{screen}_{name}")
        assert client.get(url).status_code == 403
        assert client.post(url, a.post_data(screen)).status_code == 403
    assert MODELS[screen].objects.count() == before


@pytest.mark.parametrize("screen", SCREENS)
def test_a_superuser_without_assignment_gets_403(client, screen):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse(f"academic:{screen}_list")).status_code == 403


def test_the_plan_list_shows_only_the_managers_faculties(client, a, b):
    """A manager of A sees A's plan and not B's."""
    manager_of(client, a.faculty)
    page = client.get(reverse("academic:studyplan_list")).content.decode()
    assert "Curso A" in page and "Curso B" not in page


def test_the_subject_list_shows_only_the_managers_faculties(client, a, b):
    """A manager of A sees A's subjects and not B's."""
    a.subject("SA")
    b.subject("SB")
    manager_of(client, a.faculty)
    page = client.get(reverse("academic:subject_list")).content.decode()
    assert "Disciplina SA" in page and "Disciplina SB" not in page


@pytest.mark.parametrize("screen", SCREENS)
def test_a_manager_cannot_touch_another_faculty_object(client, a, b, screen):
    """Editing or deleting an object of B as a manager of A gives 403 and changes nothing."""
    item = b.item(screen)
    manager_of(client, a.faculty)
    before = MODELS[screen].objects.count()
    for action in ("update", "delete"):
        url = reverse(f"academic:{screen}_{action}", kwargs={"pk": item.pk})
        assert client.get(url).status_code == 403
        assert client.post(url, {**b.post_data(screen), "reason": "x"}).status_code == 403
    assert MODELS[screen].objects.count() == before
    assert not AuditEntry.objects.exists()


@pytest.mark.parametrize("screen", SCREENS)
def test_creating_in_another_faculty_is_refused(client, a, b, screen):
    """The form only offers the manager's courses and plans and the server rejects the rest."""
    manager_of(client, a.faculty)
    response = client.post(reverse(f"academic:{screen}_create"), b.post_data(screen))
    assert response.status_code == 200
    assert SCOPE_FIELD[screen] in response.context["form"].errors
    assert not AuditEntry.objects.exists()


def test_creating_a_plan_is_audited(client, a):
    """A new plan version leaves one audit entry."""
    manager_of(client, a.faculty)
    client.post(reverse("academic:studyplan_create"), a.post_data("studyplan"))
    entry = AuditEntry.objects.get()
    assert entry.action == "create" and entry.entity == "academic.studyplan"


def test_a_second_plan_for_the_same_course_and_year_is_a_form_error(client, a):
    """A course has one plan version per start year."""
    manager_of(client, a.faculty)
    response = client.post(
        reverse("academic:studyplan_create"),
        {"course": a.course.pk, "academic_year": a.year.pk},
    )
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()


def test_creating_a_subject_is_audited_and_may_use_a_coordination_of_another_faculty(client, a, b):
    """Transversal subjects may be run by a coordination of another Faculty (D44)."""
    manager_of(client, a.faculty)
    data = {**a.post_data("subject"), "coordination": b.coordination.pk}
    client.post(reverse("academic:subject_create"), data)
    subject = Subject.objects.get(code="N1")
    assert subject.coordination == b.coordination
    assert AuditEntry.objects.get(entity="academic.subject").entity_id == str(subject.pk)


def test_a_duplicate_subject_code_in_a_plan_is_a_form_error(client, a):
    """The code is unique within a plan."""
    a.subject("DUP")
    manager_of(client, a.faculty)
    response = client.post(reverse("academic:subject_create"), a.post_data("subject", code="DUP"))
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()


def test_invalid_subject_values_are_form_errors(client, a):
    """Zero ECTS, semester 3 or year 0 are refused with a message, not a server error."""
    manager_of(client, a.faculty)
    for field, value in (("ects", "0"), ("semester", 3), ("curricular_year", 0)):
        data = {**a.post_data("subject"), field: value}
        response = client.post(reverse("academic:subject_create"), data)
        assert response.status_code == 200, field
    assert not Subject.objects.exists()


@pytest.mark.parametrize("screen", SCREENS)
def test_updating_needs_a_reason_and_is_audited(client, a, screen):
    """No reason: refused. With a reason: updated and logged."""
    item = a.item(screen)
    manager_of(client, a.faculty)
    url = reverse(f"academic:{screen}_update", kwargs={"pk": item.pk})
    data = a.post_data(screen, code=getattr(item, "code", "N1"), name="Renomeada")
    client.post(url, {**data, "reason": ""})
    assert not AuditEntry.objects.exists()
    client.post(url, {**data, "reason": "Correção"})
    entry = AuditEntry.objects.get(entity=f"academic.{screen}")
    assert entry.action == "update" and entry.reason == "Correção"


@pytest.mark.parametrize("screen", SCREENS)
def test_deleting_an_unused_item_is_audited(client, a, screen):
    """Deletion asks for a reason and is logged."""
    item = (
        a.item(screen)
        if screen == "subject"
        else StudyPlan.objects.create(
            course=a.course, academic_year=AcademicYear.objects.create(start_year=2031)
        )
    )
    manager_of(client, a.faculty)
    url = reverse(f"academic:{screen}_delete", kwargs={"pk": item.pk})
    client.post(url, {"reason": ""})
    assert MODELS[screen].objects.filter(pk=item.pk).exists()
    client.post(url, {"reason": "Engano"})
    assert not MODELS[screen].objects.filter(pk=item.pk).exists()
    assert AuditEntry.objects.get().action == "delete"


def test_deleting_a_plan_with_subjects_shows_a_message(client, a):
    """A plan that still has subjects is kept."""
    a.subject()
    manager_of(client, a.faculty)
    response = client.post(
        reverse("academic:studyplan_delete", kwargs={"pk": a.plan.pk}),
        {"reason": "Teste"},
        follow=True,
    )
    assert StudyPlan.objects.exists()
    assert "em uso" in response.content.decode()


def test_deleting_a_subject_with_weekly_hours_shows_a_message(client, a):
    """The weekly hours rows must be removed first (part 5 adds their editing)."""
    subject = a.subject()
    SubjectClassLoad.objects.create(
        subject=subject, class_type=ClassType.objects.get(code="T"), weekly_hours=2
    )
    manager_of(client, a.faculty)
    response = client.post(
        reverse("academic:subject_delete", kwargs={"pk": subject.pk}),
        {"reason": "Teste"},
        follow=True,
    )
    assert Subject.objects.exists()
    assert "em uso" in response.content.decode()


def test_subject_list_filters_by_semester_and_course(client, a, b):
    """The filters narrow the list by semester and by course."""
    a.subject("S1A", semester=1)
    a.subject("S2A", semester=2)
    manager_of(client, a.faculty, b.faculty)
    b.subject("SB")
    url = reverse("academic:subject_list")
    page = client.get(url, {"semester": "2"}).content.decode()
    assert "Disciplina S2A" in page and "Disciplina S1A" not in page
    page = client.get(url, {"course": a.course.pk}).content.decode()
    assert "Disciplina S1A" in page and "Disciplina SB" not in page


def test_an_htmx_request_returns_only_the_table_rows(client, a):
    """With the HX-Request header the list returns a fragment; without it, the full page."""
    a.subject("S1A")
    manager_of(client, a.faculty)
    url = reverse("academic:subject_list")
    fragment = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "S1A" in fragment and "<html" not in fragment
    full = client.get(url).content.decode()
    assert "<html" in full and "htmx" in full


def test_menu_shows_plans_and_subjects_to_a_manager_with_a_faculty(client, a):
    """The new screens appear in the menu."""
    manager_of(client, a.faculty)
    page = client.get("/").content.decode()
    assert reverse("academic:studyplan_list") in page
    assert reverse("academic:subject_list") in page
