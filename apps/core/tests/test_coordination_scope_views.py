"""View tests for ``CoordinationScopeMixin``: screens scoped by the coordination of each object.

Implements: docs/especificacao/07_arquitetura.md – permissions checked on the server; D51
(origin and destination are both checked when an object moves), D69 (who covers a
coordination). Throwaway views over ``staff.Teacher``, which carries a ``coordination``, use an
isolated registry so the real action list is not touched.
"""

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from django.views.generic import DetailView

from apps.academic.models import Coordination, Faculty
from apps.core.generic import (
    CoordinationScopeMixin,
    ScopedListView,
    ScopedModelForm,
    ScopedObjectMixin,
    ScopedUpdateView,
)
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.core.permissions import PermissionRegistry
from apps.staff.models import Category, Teacher
from config.urls import urlpatterns as project_urls

pytestmark = pytest.mark.django_db

REG = PermissionRegistry()
REG.register("t.write", {Profile.COORDINATOR, Profile.PGC_MANAGER}, write=True, scoped=True)


class Base(CoordinationScopeMixin):
    """Settings shared by the throwaway views."""

    model = Teacher
    permission_action = "t.write"
    permission_registry = REG
    success_url = "/done/"


class TeacherList(Base, ScopedListView):
    """Lists teacher names, only those of the user's coordinations."""

    def render_to_response(self, context, **kwargs):
        """Return the visible names, comma separated."""
        return HttpResponse(",".join(t.name for t in context["object_list"]))


class TeacherDetail(Base, ScopedObjectMixin, DetailView):
    """Shows one teacher name after the origin check."""

    def render_to_response(self, context, **kwargs):
        """Return the name."""
        return HttpResponse(self.object.name)


class MoveForm(ScopedModelForm):
    """Lets the user change only the coordination of a teacher."""

    scope_field = "coordination"

    class Meta:
        model = Teacher
        fields = ["coordination"]


class TeacherMove(Base, ScopedUpdateView):
    """Moves a teacher to another coordination; checks origin and destination."""

    form_class = MoveForm

    def render_to_response(self, context, **kwargs):
        """Return the form errors as plain text (the page template is not under test)."""
        return HttpResponse(str(context["form"].errors), status=200)


# The project urls stay, because the 403 page extends the base template and links to them.
urlpatterns = [
    path("t/list/", TeacherList.as_view(), name="t_list"),
    path("t/<int:pk>/", TeacherDetail.as_view(), name="t_detail"),
    path("t/<int:pk>/move/", TeacherMove.as_view(), name="t_move"),
    *project_urls,
]


@pytest.fixture(autouse=True)
def urls():
    """Serve the throwaway views for every test of this module."""
    with override_settings(ROOT_URLCONF=__name__):
        yield


@pytest.fixture
def world():
    """Two coordinations in F1, one in F2, and a teacher in each."""
    f1 = Faculty.objects.create(name="F1", code="F1")
    f2 = Faculty.objects.create(name="F2", code="F2")
    coords = {
        "c1": Coordination.objects.create(faculty=f1, name="C1"),
        "c2": Coordination.objects.create(faculty=f1, name="C2"),
        "c3": Coordination.objects.create(faculty=f2, name="C3"),
    }
    doctor = Category.objects.get(name="Doutor")
    teachers = {
        key: Teacher.objects.create(
            identifier=key,
            name=f"Docente {key}",
            coordination=coord,
            category=doctor,
            teacher_type=Teacher.Type.FULL_TIME,
        )
        for key, coord in coords.items()
    }
    return {"faculties": (f1, f2), "coords": coords, "teachers": teachers}


def login(client, profile, kind, scope_id):
    """Log in a user holding one assignment."""
    user = get_user_model().objects.create_user(username="u", password="x")
    RoleAssignment.objects.create(user=user, profile=profile, scope_kind=kind, scope_id=scope_id)
    client.force_login(user)
    return user


def test_the_list_shows_only_the_teachers_of_the_users_coordinations(client, world):
    """A coordinator of C1 sees C1's teacher only; a manager of F1 sees C1 and C2."""
    login(client, Profile.COORDINATOR, ScopeKind.COORDINATION, world["coords"]["c1"].pk)
    assert client.get(reverse("t_list")).content.decode() == "Docente c1"
    client.logout()
    login_manager = get_user_model().objects.create_user(username="m", password="x")
    RoleAssignment.objects.create(
        user=login_manager,
        profile=Profile.PGC_MANAGER,
        scope_kind=ScopeKind.FACULTY,
        scope_id=world["faculties"][0].pk,
    )
    client.force_login(login_manager)
    names = set(client.get(reverse("t_list")).content.decode().split(","))
    assert names == {"Docente c1", "Docente c2"}


def test_a_user_without_any_coordination_gets_403(client, world):
    """A manager of a Faculty with no coordination, or a role of the wrong kind, gets 403."""
    empty = Faculty.objects.create(name="F3", code="F3")
    login(client, Profile.PGC_MANAGER, ScopeKind.FACULTY, empty.pk)
    assert client.get(reverse("t_list")).status_code == 403


def test_anonymous_visitors_are_sent_to_the_login(client, world):
    """No session: redirected to the login page."""
    response = client.get(reverse("t_list"))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_requesting_an_object_of_another_coordination_by_its_id_gives_403(client, world):
    """The id in the URL is not trusted: the object's own coordination decides (IDOR)."""
    login(client, Profile.COORDINATOR, ScopeKind.COORDINATION, world["coords"]["c1"].pk)
    own = world["teachers"]["c1"].pk
    assert client.get(reverse("t_detail", kwargs={"pk": own})).status_code == 200
    for key in ("c2", "c3"):  # a sibling in the same Faculty, and one in another Faculty
        other = world["teachers"][key].pk
        assert client.get(reverse("t_detail", kwargs={"pk": other})).status_code == 403
        assert client.get(reverse("t_move", kwargs={"pk": other})).status_code == 403


def test_moving_an_object_needs_both_origin_and_destination(client, world):
    """A coordinator of C1 cannot move their teacher into C2: the destination is refused."""
    login(client, Profile.COORDINATOR, ScopeKind.COORDINATION, world["coords"]["c1"].pk)
    teacher = world["teachers"]["c1"]
    response = client.post(
        reverse("t_move", kwargs={"pk": teacher.pk}),
        {"coordination": world["coords"]["c2"].pk, "reason": "x"},
    )
    assert response.status_code == 200 and "coordination" in response.content.decode()
    teacher.refresh_from_db()
    assert teacher.coordination_id == world["coords"]["c1"].pk


def test_a_manager_of_both_may_move_between_coordinations_of_their_faculties(client, world):
    """With cover over origin and destination the move is saved."""
    f1, f2 = world["faculties"]
    user = login(client, Profile.PGC_MANAGER, ScopeKind.FACULTY, f1.pk)
    RoleAssignment.objects.create(
        user=user, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.FACULTY, scope_id=f2.pk
    )
    teacher = world["teachers"]["c1"]
    response = client.post(
        reverse("t_move", kwargs={"pk": teacher.pk}),
        {"coordination": world["coords"]["c3"].pk, "reason": "Mudança"},
    )
    assert response.status_code == 302
    teacher.refresh_from_db()
    assert teacher.coordination_id == world["coords"]["c3"].pk
