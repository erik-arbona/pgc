"""View tests for the teacher screens, limited to the manager's Faculties (T3.1, part 3).

Implements: docs/especificacao/02_perfis_e_dados.md – teachers entered by the PGC manager;
D40, D50, D51, D56 (three teacher types; positions only for full-time teachers).
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.academic.models import Coordination, Faculty
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.staff.models import Category, Position, Teacher, TeacherPosition

pytestmark = pytest.mark.django_db


class Setup:
    """A Faculty with a coordination."""

    def __init__(self, code):
        self.faculty = Faculty.objects.create(name=f"Faculdade {code}", code=code)
        self.coordination = Coordination.objects.create(faculty=self.faculty, name=f"Coord {code}")

    def teacher(self, identifier="D001", name="Ana Silva", **overrides):
        """Create a full-time teacher of this Faculty."""
        data = dict(
            identifier=identifier,
            name=name,
            coordination=self.coordination,
            category=Category.objects.get(name="Doutor"),
            teacher_type=Teacher.Type.FULL_TIME,
        )
        data.update(overrides)
        return Teacher.objects.create(**data)

    def post_data(self, identifier="N001", name="Novo Docente", **overrides):
        """Valid POST data for the teacher form."""
        data = {
            "identifier": identifier,
            "name": name,
            "coordination": self.coordination.pk,
            "category": Category.objects.get(name="Doutor").pk,
            "teacher_type": "full_time",
            "is_active": "on",
            "reason": "",
        }
        data.update(overrides)
        return data


@pytest.fixture
def a():
    """Faculty A."""
    return Setup("A")


@pytest.fixture
def b():
    """Faculty B."""
    return Setup("B")


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


def test_anonymous_visitors_are_redirected_to_login(client):
    """The list requires a session."""
    response = client.get(reverse("staff:teacher_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, a, profile):
    """Only the PGC manager reaches the teacher screens."""
    client.force_login(make_user(profile))
    for name in ("list", "create"):
        url = reverse(f"staff:teacher_{name}")
        assert client.get(url).status_code == 403
        assert client.post(url, a.post_data()).status_code == 403
    assert not Teacher.objects.exists()


def test_a_manager_with_no_assigned_faculty_gets_403(client):
    """Without any Faculty assignment there is nothing to manage."""
    user = get_user_model().objects.create_user(username="sem", password="x")
    RoleAssignment.objects.create(
        user=user, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.NONE, scope_id=None
    )
    client.force_login(user)
    assert client.get(reverse("staff:teacher_list")).status_code == 403


def test_a_superuser_without_assignment_gets_403(client):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse("staff:teacher_list")).status_code == 403


def test_the_list_shows_only_the_managers_faculties(client, a, b):
    """A manager of A sees A's teachers and not B's."""
    a.teacher("A1", "Docente da A")
    b.teacher("B1", "Docente da B")
    manager_of(client, a.faculty)
    page = client.get(reverse("staff:teacher_list")).content.decode()
    assert "Docente da A" in page and "Docente da B" not in page


def test_the_list_filters_by_type_activity_and_coordination(client, a, b):
    """The filters narrow the list."""
    a.teacher("A1", "Tempo Inteiro")
    a.teacher("A2", "Colaborador X", teacher_type=Teacher.Type.HABITUAL_COLLABORATOR)
    a.teacher("A3", "Inativo Y", is_active=False)
    manager_of(client, a.faculty, b.faculty)
    b.teacher("B1", "Docente da B")
    url = reverse("staff:teacher_list")
    page = client.get(url, {"teacher_type": "habitual_collaborator"}).content.decode()
    assert "Colaborador X" in page and "Tempo Inteiro" not in page
    page = client.get(url, {"active": "0"}).content.decode()
    assert "Inativo Y" in page and "Colaborador X" not in page
    page = client.get(url, {"coordination": b.coordination.pk}).content.decode()
    assert "Docente da B" in page and "Tempo Inteiro" not in page


def test_an_htmx_request_returns_only_the_results(client, a):
    """With the HX-Request header the list is a fragment; without it, the full page."""
    a.teacher("A1", "Ana Fragmento")
    manager_of(client, a.faculty)
    url = reverse("staff:teacher_list")
    fragment = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "Ana Fragmento" in fragment and "<html" not in fragment
    full = client.get(url).content.decode()
    assert "<html" in full and "htmx" in full


def test_a_manager_cannot_touch_another_faculty_teacher(client, a, b):
    """Editing or deleting B's teacher as a manager of A gives 403 and changes nothing."""
    teacher = b.teacher()
    manager_of(client, a.faculty)
    for action in ("update", "delete"):
        url = reverse(f"staff:teacher_{action}", kwargs={"pk": teacher.pk})
        assert client.get(url).status_code == 403
        assert client.post(url, {**b.post_data(), "reason": "x"}).status_code == 403
    assert Teacher.objects.count() == 1
    assert not AuditEntry.objects.exists()


def test_creating_in_another_faculty_is_refused(client, a, b):
    """The form only offers the manager's coordinations."""
    manager_of(client, a.faculty)
    response = client.post(reverse("staff:teacher_create"), b.post_data())
    assert response.status_code == 200
    assert "coordination" in response.context["form"].errors
    assert not Teacher.objects.exists()


def test_creating_a_teacher_is_audited(client, a):
    """A new teacher leaves one audit entry with the actor."""
    manager_of(client, a.faculty)
    client.post(reverse("staff:teacher_create"), a.post_data())
    teacher = Teacher.objects.get()
    entry = AuditEntry.objects.get()
    assert (entry.action, entry.entity_id, entry.actor.username) == (
        "create",
        str(teacher.pk),
        "gestor",
    )


def test_a_duplicate_identifier_ignoring_case_is_a_form_error(client, a):
    """The identifier is unique in the University whatever the letter case."""
    a.teacher("abc1")
    manager_of(client, a.faculty)
    response = client.post(reverse("staff:teacher_create"), a.post_data(identifier="ABC1"))
    assert response.status_code == 200
    assert response.context["form"].non_field_errors() or response.context["form"].errors
    assert Teacher.objects.count() == 1


def test_an_inactive_category_is_not_offered_for_a_new_teacher(client, a):
    """Deactivated categories cannot be given to new teachers."""
    old = Category.objects.create(code="OLD", name="Antiga", is_active=False)
    manager_of(client, a.faculty)
    response = client.post(reverse("staff:teacher_create"), a.post_data(category=old.pk))
    assert response.status_code == 200
    assert "category" in response.context["form"].errors


def test_updating_needs_a_reason_and_is_audited(client, a):
    """No reason: refused. With a reason: updated with old and new values."""
    teacher = a.teacher(name="Velho Nome")
    manager_of(client, a.faculty)
    url = reverse("staff:teacher_update", kwargs={"pk": teacher.pk})
    data = a.post_data(identifier=teacher.identifier, name="Novo Nome")
    client.post(url, data)
    teacher.refresh_from_db()
    assert teacher.name == "Velho Nome" and not AuditEntry.objects.exists()
    client.post(url, {**data, "reason": "Nome corrigido"})
    entry = AuditEntry.objects.get()
    assert (entry.old_value["name"], entry.new_value["name"]) == ("Velho Nome", "Novo Nome")
    assert entry.reason == "Nome corrigido"


def test_moving_to_another_faculty_needs_both(client, a, b):
    """A manager of A alone cannot move a teacher to B; a manager of A and B can."""
    teacher = a.teacher()
    manager_of(client, a.faculty)
    url = reverse("staff:teacher_update", kwargs={"pk": teacher.pk})
    data = {**b.post_data(identifier=teacher.identifier), "reason": "Mudança"}
    assert "coordination" in client.post(url, data).context["form"].errors
    manager_of(client, a.faculty, b.faculty, username="gestor2")
    client.post(url, data)
    teacher.refresh_from_db()
    assert teacher.coordination == b.coordination


def test_a_teacher_keeping_positions_cannot_become_a_collaborator(client, a):
    """With the position still ticked, the type change is a form error on the positions."""
    teacher = a.teacher()
    chief = Position.objects.create(name="Chefe")
    TeacherPosition.objects.create(teacher=teacher, position=chief)
    manager_of(client, a.faculty)
    response = client.post(
        reverse("staff:teacher_update", kwargs={"pk": teacher.pk}),
        {
            **a.post_data(identifier=teacher.identifier, teacher_type="habitual_collaborator"),
            "positions": [chief.pk],
            "reason": "Mudou de regime",
        },
    )
    assert response.status_code == 200
    assert "positions" in response.context["form"].errors
    teacher.refresh_from_db()
    assert teacher.teacher_type == Teacher.Type.FULL_TIME


def test_deleting_needs_a_reason_and_is_audited(client, a):
    """Deletion asks for a reason and is logged."""
    teacher = a.teacher()
    manager_of(client, a.faculty)
    url = reverse("staff:teacher_delete", kwargs={"pk": teacher.pk})
    client.post(url, {"reason": ""})
    assert Teacher.objects.exists()
    client.post(url, {"reason": "Engano"})
    assert not Teacher.objects.exists()
    assert AuditEntry.objects.get().action == "delete"


def test_deleting_a_teacher_audits_the_position_rows_first(client, a):
    """The position assignments are logged, not silently cascaded."""
    teacher = a.teacher()
    TeacherPosition.objects.create(teacher=teacher, position=Position.objects.create(name="Chefe"))
    manager_of(client, a.faculty)
    client.post(reverse("staff:teacher_delete", kwargs={"pk": teacher.pk}), {"reason": "Saiu"})
    deleted = AuditEntry.objects.filter(action="delete")
    assert sorted(deleted.values_list("entity", flat=True)) == [
        "staff.teacher",
        "staff.teacherposition",
    ]
    assert not TeacherPosition.objects.exists()


def test_deleting_a_teacher_with_an_account_role_shows_a_message(client, a):
    """A teacher that a teacher role points to is kept."""
    teacher = a.teacher()
    user = get_user_model().objects.create_user(username="ana", password="x")
    RoleAssignment.objects.create(
        user=user, profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER, scope_id=teacher.pk
    )
    manager_of(client, a.faculty, username="gestor2")
    response = client.post(
        reverse("staff:teacher_delete", kwargs={"pk": teacher.pk}),
        {"reason": "Teste"},
        follow=True,
    )
    assert Teacher.objects.exists()
    assert "em uso" in response.content.decode()
    assert not AuditEntry.objects.exists()


def test_menu_shows_the_teachers_link(client, a):
    """The teachers screen appears in the manager's menu."""
    manager_of(client, a.faculty)
    assert reverse("staff:teacher_list") in client.get("/").content.decode()
