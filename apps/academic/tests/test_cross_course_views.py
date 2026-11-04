"""View tests for the cross-course subject group screens, scoped to the manager's Faculties.

Implements: docs/especificacao/04_modelo_de_dados.md – cross-course subjects (the manager
declares them and says in which courses they are cross-course); D22, D47, D51, D55.
A group can be managed only by someone who manages the Faculty of every member.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.academic.models import (
    CrossCourseSubject,
    CrossCourseSubjectCourse,
    CrossCourseSubjectMember,
)
from apps.academic.tests.test_plan_subject_views import Setup, manager_of
from apps.core.models import AuditEntry, Profile

pytestmark = pytest.mark.django_db


@pytest.fixture
def a():
    """Faculty A with a course, a plan and a subject-capable setup."""
    return Setup("A")


@pytest.fixture
def b():
    """Faculty B with a course, a plan and a subject-capable setup."""
    return Setup("B")


@pytest.fixture
def subjects(a, b):
    """The introductory subject of each Faculty."""
    return a.subject("P1"), b.subject("P1")


def group_with(name, *members):
    """Create a group whose members are the given subjects (no audit, for fixtures)."""
    group = CrossCourseSubject.objects.create(name=name)
    for subject in members:
        CrossCourseSubjectMember.objects.create(cross_course_subject=group, subject=subject)
        CrossCourseSubjectCourse.objects.get_or_create(
            cross_course_subject=group, course=subject.study_plan.course
        )
    return group


def create_data(subjects, courses, name="Programação", reason=""):
    """POST data for the group form."""
    return {
        "name": name,
        "notes": "",
        "subjects": [s.pk for s in subjects],
        "courses": [c.pk for c in courses],
        "reason": reason,
    }


def test_anonymous_visitors_are_redirected_to_login(client):
    """The list requires a session."""
    response = client.get(reverse("academic:crosscourse_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, subjects, a, b, profile):
    """Only the PGC manager reaches these screens, including the preview."""
    client.force_login(make_user(profile))
    for name in ("crosscourse_list", "crosscourse_create", "crosscourse_preview"):
        url = reverse(f"academic:{name}")
        assert client.get(url).status_code in (403, 405)
        assert client.post(url, create_data(subjects, [a.course, b.course])).status_code == 403
    assert not CrossCourseSubject.objects.exists()


def test_a_superuser_without_assignment_gets_403(client):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse("academic:crosscourse_list")).status_code == 403


def test_the_list_shows_groups_whose_faculties_the_manager_covers(client, a, b, subjects):
    """A manager of A alone does not see a group that has a member in B."""
    sa, sb = subjects
    group_with("Só A", a.subject("P2"))
    group_with("Entre A e B", sa, sb)
    group_with("Vazio")
    manager_of(client, a.faculty)
    page = client.get(reverse("academic:crosscourse_list")).content.decode()
    assert "Só A" in page and "Vazio" in page and "Entre A e B" not in page


def test_a_manager_of_both_faculties_sees_the_shared_group(client, a, b, subjects):
    """With both Faculties assigned the cross-Faculty group is listed."""
    group_with("Entre A e B", *subjects)
    manager_of(client, a.faculty, b.faculty)
    page = client.get(reverse("academic:crosscourse_list")).content.decode()
    assert "Entre A e B" in page


def test_a_manager_cannot_touch_a_group_with_a_member_outside_their_faculties(
    client, a, b, subjects
):
    """403 on edit and delete, and nothing changes."""
    group = group_with("Entre A e B", *subjects)
    manager_of(client, a.faculty)
    for action in ("update", "delete"):
        url = reverse(f"academic:crosscourse_{action}", kwargs={"pk": group.pk})
        assert client.get(url).status_code == 403
        assert (
            client.post(
                url, {**create_data(subjects, [a.course, b.course]), "reason": "x"}
            ).status_code
            == 403
        )
    assert group.members.count() == 2
    assert not AuditEntry.objects.exists()


def test_creating_a_group_audits_the_group_and_every_row(client, a, b, subjects):
    """Name, two members and two allowed courses: five audit entries."""
    manager_of(client, a.faculty, b.faculty)
    response = client.post(
        reverse("academic:crosscourse_create"), create_data(subjects, [a.course, b.course])
    )
    assert response.status_code == 302
    group = CrossCourseSubject.objects.get()
    assert group.members.count() == 2 and group.allowed_courses.count() == 2
    entities = sorted(AuditEntry.objects.values_list("entity", flat=True))
    assert entities == sorted(
        [
            "academic.crosscoursesubject",
            "academic.crosscoursesubjectmember",
            "academic.crosscoursesubjectmember",
            "academic.crosscoursesubjectcourse",
            "academic.crosscoursesubjectcourse",
        ]
    )


def test_declared_in_two_courses_and_refused_in_a_third(client, a, b):
    """Three member courses, two allowed: the third is a member but not allowed (D22)."""
    c = Setup("C")
    members = [a.subject("P1"), b.subject("P1"), c.subject("P1")]
    manager_of(client, a.faculty, b.faculty, c.faculty)
    client.post(reverse("academic:crosscourse_create"), create_data(members, [a.course, b.course]))
    group = CrossCourseSubject.objects.get()
    assert group.members.count() == 3
    assert set(group.allowed_courses.values_list("course_id", flat=True)) == {
        a.course.pk,
        b.course.pk,
    }


def test_a_group_with_a_single_course_is_a_form_error(client, a, subjects):
    """At least two courses are needed; nothing is saved."""
    manager_of(client, a.faculty, subjects[1].study_plan.course.faculty)
    second = a.subject("P2")
    response = client.post(
        reverse("academic:crosscourse_create"), create_data([subjects[0], second], [a.course])
    )
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    assert not CrossCourseSubject.objects.exists()
    assert not AuditEntry.objects.exists()


def test_an_allowed_course_that_is_not_a_member_course_is_a_form_error(client, a, b):
    """The allowed courses must be courses of the members."""
    c = Setup("C")
    manager_of(client, a.faculty, b.faculty, c.faculty)
    response = client.post(
        reverse("academic:crosscourse_create"),
        create_data([a.subject("P1"), b.subject("P1")], [a.course, b.course, c.course]),
    )
    assert response.status_code == 200
    assert not CrossCourseSubject.objects.exists()


def test_a_subject_of_another_faculty_is_not_offered(client, a, b, subjects):
    """The manager of A cannot put B's subject into a group."""
    manager_of(client, a.faculty)
    response = client.post(
        reverse("academic:crosscourse_create"), create_data(subjects, [a.course, b.course])
    )
    assert response.status_code == 200
    assert "subjects" in response.context["form"].errors


def test_a_subject_that_is_already_in_a_group_is_not_offered(client, a, b, subjects):
    """A subject belongs to at most one group (D47)."""
    group_with("Primeiro", subjects[0])
    manager_of(client, a.faculty, b.faculty)
    response = client.post(
        reverse("academic:crosscourse_create"), create_data(subjects, [a.course, b.course])
    )
    assert response.status_code == 200
    assert "subjects" in response.context["form"].errors
    assert CrossCourseSubject.objects.count() == 1


def test_updating_members_needs_a_reason_and_audits_each_row(client, a, b, subjects):
    """Removing one member and adding another logs a delete and a create, with the reason."""
    c = Setup("C")
    group = group_with("Programação", *subjects)
    manager_of(client, a.faculty, b.faculty, c.faculty)
    url = reverse("academic:crosscourse_update", kwargs={"pk": group.pk})
    new_members = [subjects[0], c.subject("P1")]
    data = create_data(new_members, [a.course, c.course])
    client.post(url, {**data, "reason": ""})
    assert group.members.count() == 2 and not AuditEntry.objects.exists()
    client.post(url, {**data, "reason": "Plano novo"})
    assert set(group.members.values_list("subject_id", flat=True)) == {s.pk for s in new_members}
    actions = list(
        AuditEntry.objects.filter(entity="academic.crosscoursesubjectmember")
        .order_by("pk")
        .values_list("action", flat=True)
    )
    assert sorted(actions) == ["create", "delete"]
    assert all(e.reason == "Plano novo" for e in AuditEntry.objects.all())


def test_deleting_a_group_audits_its_rows_first(client, a, b, subjects):
    """Deletion needs a reason and logs every member, course and the group."""
    group = group_with("Programação", *subjects)
    manager_of(client, a.faculty, b.faculty)
    url = reverse("academic:crosscourse_delete", kwargs={"pk": group.pk})
    client.post(url, {"reason": ""})
    assert CrossCourseSubject.objects.exists()
    client.post(url, {"reason": "Engano"})
    assert not CrossCourseSubject.objects.exists()
    deleted = AuditEntry.objects.filter(action="delete")
    assert deleted.count() == 5  # 2 members + 2 courses + the group
    assert not CrossCourseSubjectMember.objects.exists()


def test_the_preview_warns_when_the_semester_differs(client, a, b):
    """HTMX preview: the 1st-semester and 2nd-semester subjects trigger a warning."""
    first = a.subject("P1", semester=1)
    second = b.subject("P1", semester=2)
    manager_of(client, a.faculty, b.faculty)
    response = client.post(
        reverse("academic:crosscourse_preview"),
        create_data([first, second], [a.course, b.course]),
        HTTP_HX_REQUEST="true",
    )
    page = response.content.decode()
    assert response.status_code == 200
    assert "semestre" in page.lower()
    assert "<html" not in page


def test_the_preview_reports_blocking_errors(client, a):
    """One course only: the preview says the group is not valid yet."""
    first, second = a.subject("P1"), a.subject("P2")
    manager_of(client, a.faculty)
    page = client.post(
        reverse("academic:crosscourse_preview"),
        create_data([first, second], [a.course]),
        HTTP_HX_REQUEST="true",
    ).content.decode()
    assert "pelo menos dois cursos" in page


def test_the_preview_ignores_subjects_outside_the_managers_faculties(client, a, b, subjects):
    """Ids of subjects the manager cannot manage are not shown or compared."""
    manager_of(client, a.faculty)
    page = client.post(
        reverse("academic:crosscourse_preview"),
        create_data(subjects, [a.course, b.course]),
        HTTP_HX_REQUEST="true",
    ).content.decode()
    assert "Faculdade B" not in page


def test_menu_shows_the_groups_link(client, a):
    """The groups screen appears in the manager's menu."""
    manager_of(client, a.faculty)
    assert reverse("academic:crosscourse_list") in client.get("/").content.decode()
