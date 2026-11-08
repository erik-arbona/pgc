"""Tests for the view by course: rows, shared subjects, what is missing, filters, indicators (T6.7).

Implements: docs/especificacao/07_arquitetura.md – view by course; docs/backlog_fase2.md T6.7;
D20, D47 (transversal subjects), D70 (a merge counts once), D84 (a coordinator reads, and only
writes what is theirs), D103.
"""

# The fixture comes from the cross-course tests; F811 flags every test that uses it.
# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.academic.models import Subject, SubjectClassLoad
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.dsd.course_rules import RowFact, hours_counted_once, indicators
from apps.dsd.course_view import CourseFilters, course_view
from apps.dsd.services import assign_teacher, merge_units
from apps.dsd.tests.test_merge_cross_course import unit_of, world  # noqa: F401
from apps.staff.models import Category, Teacher

pytestmark = pytest.mark.django_db

D = Decimal


# --- the pure rules ----------------------------------------------------------------------------


def test_the_hours_of_a_unit_counted_in_another_course_are_not_counted_again():
    """A guest row is the same lesson as the host's: it counts once (D70)."""
    rows = [
        RowFact(1, D("2"), "Doutor", 7, guest=False),
        RowFact(1, D("2"), "Doutor", 7, guest=True),
    ]
    assert hours_counted_once(rows) == D("2.00")


def test_a_group_unit_counts_each_time_it_exists():
    """Two units (two groups) of 3 h are 6 h."""
    rows = [
        RowFact(1, D("3"), "Doutor", 7, guest=False),
        RowFact(2, D("3"), "Doutor", 7, guest=False),
    ]
    assert hours_counted_once(rows) == D("6.00")


def test_the_indicators_give_hours_by_category_and_the_number_of_teachers():
    """Hours of each category of teacher and how many different teachers."""
    rows = [
        RowFact(1, D("2"), "Doutor", 7, guest=False),
        RowFact(2, D("3"), "Mestre", 8, guest=False),
        RowFact(3, D("4"), "Doutor", 7, guest=False),
        RowFact(4, D("5"), "", None, guest=False),  # no teacher yet
        RowFact(1, D("2"), "Doutor", 7, guest=True),  # the same lesson seen from the other course
    ]
    result = indicators(rows)
    assert result.hours_by_category == {"Doutor": D("6.00"), "Mestre": D("3.00")}
    assert result.teachers == 2
    assert result.hours_without_teacher == D("5.00")


# --- the data of a course ----------------------------------------------------------------------


def teacher(world, identifier="DOC", category="Doutor"):
    """A teacher of the coordination."""
    return Teacher.objects.create(
        identifier=identifier,
        name=f"Docente {identifier}",
        coordination=world["coordination"],
        category=Category.objects.get(name=category),
        teacher_type=Teacher.Type.FULL_TIME,
    )


def view_of(world, course="EIC", **filters):
    """The view of a course of the DSD."""
    return course_view(world["dsd"], world["courses"][course], CourseFilters(**filters))


def lesson_codes(result):
    """The (subject code, class type) of each own row."""
    return sorted((r.subject.code, r.class_type) for r in result.rows if not r.guest)


def test_a_course_lists_the_units_of_its_subjects(world):
    """EIC has A1 with theory and practice; EEC has B1."""
    assert lesson_codes(view_of(world, "EIC")) == [("A1", "P"), ("A1", "T")]
    assert lesson_codes(view_of(world, "EEC")) == [("B1", "P"), ("B1", "T")]


def test_the_transversal_subjects_are_marked_as_shared_in_every_course(world):
    """Even before any merge: the subject belongs to a transversal group (D47)."""
    for course in ("EIC", "EEC"):
        assert all(row.shared for row in view_of(world, course).rows)


def test_a_subject_that_is_not_transversal_is_not_shared(world):
    """A subject outside the group, in the same plan."""
    other = Subject.objects.create(
        study_plan=world["plans"]["EIC"],
        code="A2",
        name="Disciplina A2",
        ects=D("6"),
        curricular_year=1,
        semester=1,
        coordination=world["coordination"],
        semester_hours=D("60"),
    )
    SubjectClassLoad.objects.create(subject=other, class_type=world["T"], weekly_hours=D("4"))
    from apps.dsd.services import generate_offerings

    generate_offerings(world["manager"], [world["semester"]])
    rows = {r.subject.code: r.shared for r in view_of(world, "EIC").rows}
    assert rows["A2"] is False and rows["A1"] is True


def test_a_merged_lesson_is_one_row_in_the_host_and_a_guest_row_in_the_other_course(world):
    """EIC and EEC share the theory class: counted in the host, shown in the other (D70, D92)."""
    merge_units(world["manager"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 80)
    eic = view_of(world, "EIC")
    eec = view_of(world, "EEC")
    host = next(r for r in eic.rows if r.class_type == "T")
    assert len(host.groups) == 2
    guest = next(r for r in eec.rows if r.guest)
    assert guest.host_subject.code == "A1" and guest.class_type == "T"
    assert not any(r.class_type == "T" and not r.guest for r in eec.rows)


def test_the_total_hours_of_a_course_count_a_shared_lesson_once(world):
    """EIC: theory 2 h (shared) + practice 3 h = 5 h; EEC: only its practice, 3 h."""
    merge_units(world["manager"], [unit_of(world, "EIC"), unit_of(world, "EEC")], 80)
    assert view_of(world, "EIC").total_hours == D("5.00")
    assert view_of(world, "EEC").total_hours == D("3.00")


def test_a_unit_without_a_teacher_is_flagged_and_one_with_a_teacher_is_not(world):
    """What is missing stands out."""
    doc = teacher(world)
    assign_teacher(world["manager"], unit_of(world, "EIC"), doc)
    rows = {r.class_type: r for r in view_of(world, "EIC").rows}
    assert rows["T"].teacher == doc and not rows["T"].without_teacher
    assert rows["P"].without_teacher


def test_a_subject_of_the_plan_with_no_turma_is_listed_as_missing(world):
    """A second-year subject: no turma attends it, so it has no offering."""
    Subject.objects.create(
        study_plan=world["plans"]["EIC"],
        code="A3",
        name="Disciplina A3",
        ects=D("6"),
        curricular_year=2,
        semester=1,
        coordination=world["coordination"],
        semester_hours=D("60"),
    )
    assert [s.code for s in view_of(world, "EIC").without_turma] == ["A3"]
    assert view_of(world, "EEC").without_turma == []


def test_the_filters_combine(world):
    """Class type, teacher, semester and year narrow the rows."""
    doc = teacher(world)
    assign_teacher(world["manager"], unit_of(world, "EIC"), doc)
    assert {r.class_type for r in view_of(world, "EIC", class_type="T").rows} == {"T"}
    assert {r.class_type for r in view_of(world, "EIC", teacher_id=doc.pk).rows} == {"T"}
    assert view_of(world, "EIC", semester=2).rows == []
    assert view_of(world, "EIC", curricular_year=2).rows == []
    assert view_of(world, "EIC", class_type="P", teacher_id=doc.pk).rows == []
    turma = world["turmas"]["EIC"]
    assert len(view_of(world, "EIC", class_group_id=turma.pk).rows) == 2


def test_the_indicators_use_the_rows_of_the_course(world):
    """5 h given by one doctor: one teacher, 5 h in 'Doutor'."""
    doc = teacher(world)
    for class_type in ("T", "P"):
        assign_teacher(world["manager"], unit_of(world, "EIC", class_type), doc)
    result = view_of(world, "EIC")
    assert result.indicators.hours_by_category == {"Doutor": D("5.00")}
    assert result.indicators.teachers == 1


# --- the screens -------------------------------------------------------------------------------


def url(world, course="EIC"):
    """The page of a course."""
    return reverse("dsd:course_view", args=[world["dsd"].pk, world["courses"][course].pk])


def other_faculty_user(django_user_model, profile, name):
    """A user of another Faculty (with a coordination there for the coordinator)."""
    from apps.academic.models import Coordination, Faculty

    faculty = Faculty.objects.create(name=f"Faculdade {name}", code=name.upper())
    coordination = Coordination.objects.create(faculty=faculty, name=f"Coordenação {name}")
    user = django_user_model.objects.create_user(username=name, password="x")
    if profile == Profile.COORDINATOR:
        kind, scope = ScopeKind.COORDINATION, coordination.pk
    else:
        kind, scope = ScopeKind.FACULTY, faculty.pk
    RoleAssignment.objects.create(user=user, profile=profile, scope_kind=kind, scope_id=scope)
    return user


def test_the_coordinator_the_manager_and_the_board_of_the_faculty_read_the_course(
    world, client, django_user_model
):
    """Coordinators read any course (D84); the manager and the board, those of their Faculty."""
    board = django_user_model.objects.create_user(username="ce", password="x")
    RoleAssignment.objects.create(
        user=board,
        profile=Profile.EXECUTIVE_BOARD,
        scope_kind=ScopeKind.FACULTY,
        scope_id=world["faculty"].pk,
    )
    for user in (world["coordinator"], world["manager"], board):
        client.force_login(user)
        assert client.get(url(world)).status_code == 200


def test_a_coordinator_of_another_faculty_still_reads_in_read_only(
    world, client, django_user_model
):
    """The rule 'reads everything, writes only what is theirs' (D84)."""
    outsider = other_faculty_user(django_user_model, Profile.COORDINATOR, "x1")
    client.force_login(outsider)
    assert client.get(url(world)).status_code == 200


def test_the_manager_and_the_board_of_another_faculty_do_not_read_it(
    world, client, django_user_model
):
    """Their scope is their own Faculty."""
    for profile, name in ((Profile.PGC_MANAGER, "x2"), (Profile.EXECUTIVE_BOARD, "x3")):
        client.force_login(other_faculty_user(django_user_model, profile, name))
        assert client.get(url(world)).status_code == 403


def test_a_teacher_account_and_anonymous_users_do_not_read_it(world, client, django_user_model):
    """Teachers read only their own sheet; anonymous users go to the login."""
    teacher_user = django_user_model.objects.create_user(username="td", password="x")
    RoleAssignment.objects.create(
        user=teacher_user, profile=Profile.TEACHER, scope_kind=ScopeKind.NONE, scope_id=None
    )
    assert client.get(url(world)).status_code == 302
    client.force_login(teacher_user)
    assert client.get(url(world)).status_code == 403


def test_the_page_shows_the_shared_mark_the_missing_teacher_and_the_missing_turma(world, client):
    """The three things the specification asks to highlight."""
    Subject.objects.create(
        study_plan=world["plans"]["EIC"],
        code="A3",
        name="Disciplina A3",
        ects=D("6"),
        curricular_year=2,
        semester=1,
        coordination=world["coordination"],
        semester_hours=D("60"),
    )
    client.force_login(world["coordinator"])
    html = client.get(url(world)).content.decode()
    assert "partilhada" in html
    assert "sem docente" in html
    assert "A3" in html and "sem turma" in html


def test_the_page_filters_by_the_query_string(world, client):
    """A filter in the URL narrows the table."""
    client.force_login(world["coordinator"])
    html = client.get(url(world), {"class_type": "T"}).content.decode()
    assert html.count('class="lesson"') == 1


def test_a_filter_that_is_not_a_number_is_ignored_not_a_server_error(world, client):
    """Junk in the query string never breaks the page."""
    client.force_login(world["coordinator"])
    assert client.get(url(world), {"teacher": "x", "semester": "9", "year": "y"}).status_code == 200


def test_the_page_is_read_only(world, client):
    """No change links: it is a view to read and compare."""
    client.force_login(world["manager"])
    html = client.get(url(world)).content.decode()
    for forbidden in ("/merge/", "/separate/", "/inline/", "/room/"):
        assert forbidden not in html


def test_the_list_of_courses_shows_the_courses_the_user_may_read(world, client):
    """With a link to each."""
    client.force_login(world["coordinator"])
    html = client.get(reverse("dsd:course_list", args=[world["dsd"].pk])).content.decode()
    assert url(world, "EIC") in html and url(world, "EEC") in html


def test_a_course_with_no_plan_and_no_units_renders_an_empty_page(world, client):
    """A new course: nothing to list, nothing missing, and no error."""
    from apps.academic.models import Course

    empty = Course.objects.create(faculty=world["faculty"], name="Curso vazio", level="bachelor")
    client.force_login(world["coordinator"])
    response = client.get(reverse("dsd:course_view", args=[world["dsd"].pk, empty.pk]))
    assert response.status_code == 200
    assert "Nenhuma aula" in response.content.decode()


def test_a_user_with_two_roles_reads_what_either_allows(world, client, django_user_model):
    """A manager of another Faculty who is also a coordinator keeps the coordinator's reading."""
    outsider = other_faculty_user(django_user_model, Profile.PGC_MANAGER, "x4")
    client.force_login(outsider)
    assert client.get(url(world)).status_code == 403
    RoleAssignment.objects.create(
        user=outsider,
        profile=Profile.COORDINATOR,
        scope_kind=ScopeKind.COORDINATION,
        scope_id=world["coordination"].pk,
    )
    assert client.get(url(world)).status_code == 200


def test_an_inactive_user_reads_nothing(world, client):
    """Deactivated accounts are refused whatever their roles."""
    world["coordinator"].is_active = False
    world["coordinator"].save()
    client.force_login(world["coordinator"])
    assert client.get(url(world)).status_code in (302, 403)


# --- review of the view by course ------------------------------------------------------------


def test_digits_that_are_not_ascii_are_ignored_in_every_query_string_of_the_dsd(world, client):
    """'²' passes str.isdigit() but not int(): it must be ignored, never a server error."""
    client.force_login(world["manager"])
    junk = {"semester": "²", "year": "²", "teacher": "²", "class_group": "²", "coordination": "²"}
    assert client.get(url(world), junk).status_code == 200
    listing = reverse("dsd:offering_list", args=[world["dsd"].pk])
    assert client.get(listing, junk).status_code == 200
    offering = world["links"]["EIC"].offering
    merge = reverse("dsd:offering_merge", args=[offering.pk])
    assert client.get(merge, {"units": ["²", "²"]}).status_code in (200, 302)


def test_the_inline_teacher_choice_ignores_digits_that_are_not_ascii(world, client):
    """A forged teacher or version made of '²' is an error in the row, not a 500."""
    from apps.dsd.tests.test_merge_cross_course import unit_of as unit

    client.force_login(world["manager"])
    target = unit(world, "EIC")
    response = client.post(
        reverse("dsd:unit_teacher_inline", args=[target.offering_id, target.pk]),
        {"teacher": "²", "seen": "²"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200


def test_the_missing_turma_list_is_not_shown_when_the_view_is_narrowed_to_a_teacher_or_a_type(
    world,
):
    """Filtering by teacher, class type or turma is about lessons, not about plan subjects."""
    Subject.objects.create(
        study_plan=world["plans"]["EIC"],
        code="A3",
        name="Disciplina A3",
        ects=D("6"),
        curricular_year=2,
        semester=1,
        coordination=world["coordination"],
        semester_hours=D("60"),
    )
    assert [s.code for s in view_of(world, "EIC").without_turma] == ["A3"]
    assert view_of(world, "EIC", class_type="T").without_turma == []
    assert view_of(world, "EIC", teacher_id=1).without_turma == []
    assert view_of(world, "EIC", class_group_id=1).without_turma == []


def test_a_unit_whose_class_type_left_the_plan_says_it_has_no_hours(world, client):
    """Instead of a bare dash that hides that the total is understated."""
    SubjectClassLoad.objects.filter(
        class_type=world["P"], subject=world["subjects"]["EIC"]
    ).delete()
    client.force_login(world["coordinator"])
    assert "sem horas no plano" in client.get(url(world)).content.decode()
