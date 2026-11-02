"""View tests for the track screens and the track field of subjects and turmas (T0.6b).

Implements: docs/especificacao/07_arquitetura.md – permissions with scope, checked on the
server; D40 (reason), D50 (UI pattern), D51 (manager limited to assigned Faculties), D75, D79.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
    Track,
)
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind

pytestmark = pytest.mark.django_db


class Setup:
    """A Faculty with a course, a 2023 plan, a 2025 plan, a coordination and a track."""

    def __init__(self, code):
        self.faculty = Faculty.objects.create(name=f"Faculdade {code}", code=code)
        self.course = Course.objects.create(
            faculty=self.faculty, name=f"Curso {code}", level="bachelor"
        )
        self.year_2023 = AcademicYear.objects.get_or_create(start_year=2023)[0]
        self.year_2025 = AcademicYear.objects.get_or_create(start_year=2025)[0]
        self.plan = StudyPlan.objects.create(course=self.course, academic_year=self.year_2023)
        self.newer_plan = StudyPlan.objects.create(course=self.course, academic_year=self.year_2025)
        self.coordination = Coordination.objects.create(faculty=self.faculty, name=f"Coord {code}")
        self.track = Track.objects.create(
            study_plan=self.plan, code=f"T{code}", name=f"Percurso {code}", first_curricular_year=4
        )

    def track_data(self, **extra):
        """Valid POST data of the track form."""
        data = {
            "study_plan": self.plan.pk,
            "code": "NOVO",
            "name": "Percurso novo",
            "first_curricular_year": 4,
            "sii_ref": "",
        }
        data.update(extra)
        return data

    def subject_data(self, track=None, code="N1", year=4, **extra):
        """Valid POST data of the subject form (4 h of T x 15 weeks = 60, D60)."""
        data = {
            "study_plan": self.plan.pk,
            "code": code,
            "name": "Nova",
            "ects": "6",
            "curricular_year": year,
            "semester": 1,
            "coordination": self.coordination.pk,
            "semester_hours": "60",
            "programme": "",
            "sii_ref": "",
            "track": track.pk if track else "",
            f"hours_{ClassType.objects.get(code='T').pk}": "4",
        }
        data.update(extra)
        return data

    def group_data(self, track=None, **extra):
        """Valid POST data of the turma creation form (intake 2023)."""
        data = {
            "course": self.course.pk,
            "intake_year": self.year_2023.pk,
            "label": "",
            "last_academic_year": "",
            "track": track.pk if track else "",
        }
        data.update(extra)
        return data


@pytest.fixture
def a():
    """Faculty A and its data."""
    return Setup("A")


@pytest.fixture
def b():
    """Faculty B and its data."""
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


# --- the track screens -------------------------------------------------------------------------


def test_anonymous_visitors_are_redirected_to_login(client):
    """The list requires a session."""
    response = client.get(reverse("academic:track_list"))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, a, profile):
    """Only the PGC manager reaches the track screens."""
    client.force_login(make_user(profile))
    assert client.get(reverse("academic:track_list")).status_code == 403
    assert client.post(reverse("academic:track_create"), a.track_data()).status_code == 403
    assert Track.objects.count() == 1


def test_the_list_shows_only_the_tracks_of_the_managers_faculties(client, a, b):
    """A manager of A sees A's tracks and not B's."""
    manager_of(client, a.faculty)
    page = client.get(reverse("academic:track_list")).content.decode()
    assert "Percurso A" in page and "Percurso B" not in page


def test_the_list_counts_the_subjects_and_turmas_of_each_track(client, a):
    """The row shows how many subjects and turmas use the track."""
    Subject.objects.create(
        study_plan=a.plan,
        code="S1",
        name="X",
        ects=Decimal("6"),
        curricular_year=4,
        semester=1,
        coordination=a.coordination,
        semester_hours=Decimal("60"),
        track=a.track,
    )
    manager_of(client, a.faculty)
    response = client.get(reverse("academic:track_list"))
    (row,) = response.context["object_list"]
    assert (row.subject_count, row.group_count) == (1, 0)


def test_a_manager_cannot_touch_a_track_of_another_faculty(client, a, b):
    """Editing or deleting B's track as a manager of A gives 403 and changes nothing."""
    manager_of(client, a.faculty)
    for action in ("update", "delete"):
        url = reverse(f"academic:track_{action}", kwargs={"pk": b.track.pk})
        assert client.get(url).status_code == 403
        assert client.post(url, {**b.track_data(), "reason": "x"}).status_code == 403
    assert Track.objects.filter(pk=b.track.pk).exists()
    assert not AuditEntry.objects.exists()


def test_creating_a_track_in_a_plan_of_another_faculty_is_refused(client, a, b):
    """The plan choices are the manager's own and the server rejects the rest."""
    manager_of(client, a.faculty)
    response = client.post(reverse("academic:track_create"), b.track_data())
    assert response.status_code == 200
    assert "study_plan" in response.context["form"].errors
    assert Track.objects.count() == 2  # only the two fixtures


def test_creating_a_track_is_audited(client, a):
    """A valid creation leaves one audit entry with the actor."""
    manager_of(client, a.faculty)
    client.post(reverse("academic:track_create"), a.track_data())
    track = Track.objects.get(code="NOVO")
    entry = AuditEntry.objects.get()
    assert (entry.action, entry.entity_id, entry.actor.username) == (
        "create",
        str(track.pk),
        "gestor",
    )


def test_a_duplicate_track_code_is_a_form_error_not_a_server_error(client, a):
    """The code is unique inside the plan."""
    manager_of(client, a.faculty)
    response = client.post(reverse("academic:track_create"), a.track_data(code=a.track.code))
    assert response.status_code == 200
    assert response.context["form"].errors
    assert Track.objects.count() == 1


def test_updating_a_track_needs_a_reason_and_is_audited(client, a):
    """No reason: refused. With a reason: updated with the old and new values."""
    manager_of(client, a.faculty)
    url = reverse("academic:track_update", kwargs={"pk": a.track.pk})
    data = a.track_data(code=a.track.code, name="Renomeado")
    client.post(url, {**data, "reason": ""})
    a.track.refresh_from_db()
    assert a.track.name == "Percurso A" and not AuditEntry.objects.exists()
    client.post(url, {**data, "reason": "Nome oficial"})
    entry = AuditEntry.objects.get()
    assert (entry.old_value["name"], entry.new_value["name"]) == ("Percurso A", "Renomeado")


def test_deleting_an_unused_track_is_audited(client, a):
    """Deletion asks for a reason and is logged."""
    manager_of(client, a.faculty)
    url = reverse("academic:track_delete", kwargs={"pk": a.track.pk})
    client.post(url, {"reason": ""})
    assert Track.objects.filter(pk=a.track.pk).exists()
    client.post(url, {"reason": "Engano"})
    assert not Track.objects.filter(pk=a.track.pk).exists()
    assert AuditEntry.objects.get().action == "delete"


def test_deleting_a_track_in_use_shows_a_message(client, a):
    """A track with a turma is kept."""
    ClassGroup.objects.create(
        course=a.course, intake_year=a.year_2023, study_plan=a.plan, track=a.track
    )
    manager_of(client, a.faculty)
    response = client.post(
        reverse("academic:track_delete", kwargs={"pk": a.track.pk}),
        {"reason": "Teste"},
        follow=True,
    )
    assert Track.objects.filter(pk=a.track.pk).exists()
    assert "em uso" in response.content.decode()
    assert not AuditEntry.objects.exists()


def test_the_menu_shows_the_tracks_to_a_manager_with_a_faculty(client, a):
    """The link appears in the menu."""
    manager_of(client, a.faculty)
    assert reverse("academic:track_list") in client.get("/").content.decode()


# --- the track in the subject form -------------------------------------------------------------


def test_the_subject_form_offers_only_the_tracks_of_the_managers_faculties(client, a, b):
    """B's track is not among the choices of a manager of A."""
    manager_of(client, a.faculty)
    response = client.get(reverse("academic:subject_create"))
    assert list(response.context["form"].fields["track"].queryset) == [a.track]


def test_a_subject_is_created_with_a_track_and_audited(client, a):
    """The chosen track is saved and appears in the audit entry."""
    manager_of(client, a.faculty)
    client.post(reverse("academic:subject_create"), a.subject_data(track=a.track))
    subject = Subject.objects.get(code="N1")
    assert subject.track == a.track
    assert AuditEntry.objects.get(entity="academic.subject").new_value["track"] == a.track.pk


def test_a_subject_without_a_track_is_common(client, a):
    """Leaving the track empty makes a common subject."""
    manager_of(client, a.faculty)
    client.post(reverse("academic:subject_create"), a.subject_data())
    assert Subject.objects.get(code="N1").track is None


def test_a_track_of_another_plan_is_a_field_error_in_the_subject_form(client, a):
    """The track belongs to the 2023 plan; the subject is in the 2025 plan."""
    manager_of(client, a.faculty)
    data = a.subject_data(track=a.track, study_plan=a.newer_plan.pk)
    response = client.post(reverse("academic:subject_create"), data)
    assert response.status_code == 200
    assert "track" in response.context["form"].errors
    assert not Subject.objects.exists()


def test_a_track_that_starts_later_is_a_field_error_in_the_subject_form(client, a):
    """A 3rd-year subject cannot belong to a track that starts in the 4th year."""
    manager_of(client, a.faculty)
    response = client.post(
        reverse("academic:subject_create"), a.subject_data(track=a.track, year=3)
    )
    assert "track" in response.context["form"].errors
    assert not Subject.objects.exists()


def test_the_subject_list_shows_the_track_or_common(client, a):
    """The 'Percurso' column shows the track code, or 'comum' for a common subject."""
    for code, track in (("C1", None), ("T1", a.track)):
        Subject.objects.create(
            study_plan=a.plan,
            code=code,
            name=f"Disc {code}",
            ects=Decimal("6"),
            curricular_year=4,
            semester=1,
            coordination=a.coordination,
            semester_hours=Decimal("60"),
            track=track,
        )
    manager_of(client, a.faculty)
    page = client.get(reverse("academic:subject_list")).content.decode()
    assert "Percurso" in page and "comum" in page and a.track.code in page


# --- the track in the turma screens ------------------------------------------------------------


def test_a_turma_is_created_with_a_track_of_the_plan_in_force(client, a):
    """Intake 2023 follows the 2023 plan, which has the track."""
    manager_of(client, a.faculty)
    client.post(reverse("academic:classgroup_create"), a.group_data(track=a.track))
    group = ClassGroup.objects.get()
    assert (group.track, group.study_plan) == (a.track, a.plan)


def test_a_turma_without_a_track_is_still_created(client, a):
    """The track is optional."""
    manager_of(client, a.faculty)
    client.post(reverse("academic:classgroup_create"), a.group_data())
    assert ClassGroup.objects.get().track is None


def test_a_track_not_in_the_plan_in_force_is_a_form_error(client, a):
    """Intake 2025 follows the 2025 plan, which does not have the 2023 plan's track."""
    manager_of(client, a.faculty)
    data = a.group_data(track=a.track, intake_year=a.year_2025.pk)
    response = client.post(reverse("academic:classgroup_create"), data)
    assert response.status_code == 200
    assert response.context["form"].errors
    assert not ClassGroup.objects.exists()


def test_the_turma_edit_form_has_no_track_field(client, a):
    """The track is fixed when the turma is created (D79)."""
    group = ClassGroup.objects.create(
        course=a.course, intake_year=a.year_2023, study_plan=a.plan, track=a.track
    )
    manager_of(client, a.faculty)
    response = client.get(reverse("academic:classgroup_update", kwargs={"pk": group.pk}))
    assert "track" not in response.context["form"].fields


def test_the_turma_list_shows_the_track(client, a):
    """The 'Percurso' column shows the track code."""
    ClassGroup.objects.create(
        course=a.course, intake_year=a.year_2023, study_plan=a.plan, track=a.track
    )
    manager_of(client, a.faculty)
    page = client.get(reverse("academic:classgroup_list")).content.decode()
    assert "Percurso" in page and a.track.code in page


def test_the_turma_form_offers_only_the_tracks_of_the_managers_faculties(client, a, b):
    """B's track is not among the choices of a manager of A when creating a turma."""
    manager_of(client, a.faculty)
    response = client.get(reverse("academic:classgroup_create"))
    assert list(response.context["form"].fields["track"].queryset) == [a.track]
