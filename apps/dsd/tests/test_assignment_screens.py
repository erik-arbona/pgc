"""Tests for the screens that give a teacher to a teaching unit (T5.1b).

Implements: docs/backlog_fase2.md T5.1; D94 (one teacher per unit), D72-D74 (the state of the load
of the teacher is shown), D86 (buttons only to who can write the cell), D40 (reason), D54.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Course,
    Enrollment,
    Faculty,
    StudyPlan,
    Subject,
    SubjectClassLoad,
)
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.dsd.models import Offering, OfferingClassGroup, TeachingUnit
from apps.dsd.services import assign_teacher, change_state, create_dsd, generate_offerings
from apps.staff.models import Category, LoadRange, Teacher

pytestmark = pytest.mark.django_db


def make_teacher(coordination, identifier, active=True):
    """A full-time teacher of a coordination."""
    return Teacher.objects.create(
        identifier=identifier,
        name=f"Docente {identifier}",
        coordination=coordination,
        category=Category.objects.get(name="Doutor"),
        teacher_type=Teacher.Type.FULL_TIME,
        is_active=active,
    )


def user_with(django_user_model, profile, kind, scope_id, username):
    """A user with one role."""
    user = django_user_model.objects.create_user(username=username, password="x")
    RoleAssignment.objects.create(user=user, profile=profile, scope_kind=kind, scope_id=scope_id)
    return user


@pytest.fixture
def world(django_user_model):
    """One turma of 30 students, a subject with T (2 h) and P (3 h), teachers and a range."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    other = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2026)}
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="EIC", level="bachelor"),
        academic_year=years[2023],
    )
    manager = user_with(django_user_model, Profile.PGC_MANAGER, ScopeKind.FACULTY, faculty.pk, "m")
    turma = ClassGroup.objects.create(
        course=plan.course, intake_year=years[2026], study_plan=plan, label="A"
    )
    Enrollment.objects.create(
        class_group=turma, academic_year=years[2026], kind="actual", students=30
    )
    subject = Subject.objects.create(
        study_plan=plan,
        code="A1",
        name="Disciplina A1",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=coordination,
        semester_hours=Decimal("75"),
    )
    for code, hours in (("T", "2"), ("P", "3")):
        SubjectClassLoad.objects.create(
            subject=subject, class_type=ClassType.objects.get(code=code), weekly_hours=hours
        )
    LoadRange.objects.create(
        kind=LoadRange.Kind.CATEGORY,
        category=Category.objects.get(name="Doutor"),
        minimum_hours=Decimal("6"),
        maximum_hours=Decimal("12"),
        valid_from=date(2020, 1, 1),
    )
    dsd = create_dsd(years[2026], manager)
    semester = dsd.semesters.get(number=1)
    generate_offerings(manager, [semester])
    return {
        "manager": manager,
        "coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, coordination.pk, "c"
        ),
        "other": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, other.pk, "o"
        ),
        "teacher_user": user_with(django_user_model, Profile.TEACHER, ScopeKind.NONE, None, "tu"),
        "semester": semester,
        "coordination": coordination,
        "offering": Offering.objects.get(),
        "link": OfferingClassGroup.objects.get(),
        "mine": make_teacher(coordination, "T1"),
        "mine2": make_teacher(coordination, "T2"),
        "foreign": make_teacher(other, "T3"),
        "inactive": make_teacher(coordination, "T4", active=False),
        "T": ClassType.objects.get(code="T"),
        "P": ClassType.objects.get(code="P"),
    }


def open_cell(world):
    """Open the semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def unit(world, class_type="T"):
    """The unit of the turma for a class type, as stored."""
    return TeachingUnit.objects.get(offering=world["offering"], class_type=world[class_type])


def page_url(world):
    """The page of the offering."""
    return reverse("dsd:offering_detail", args=[world["offering"].pk])


def teacher_url(world, class_type="T"):
    """The form to give a teacher to a unit."""
    return reverse("dsd:unit_teacher", args=[world["offering"].pk, unit(world, class_type).pk])


def post(client, world, teacher, reason="", seen=None, class_type="T"):
    """Post the teacher form."""
    return client.post(
        teacher_url(world, class_type),
        {
            "teacher": teacher.pk if teacher else "",
            "reason": reason,
            "seen": unit(world, class_type).version if seen is None else seen,
        },
    )


# --- the page ----------------------------------------------------------------------------------


def test_the_page_shows_the_teacher_and_the_state_of_their_load(client, world):
    """A teacher with 2 of at least 6 hours is below the minimum."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit(world), world["mine"])
    client.force_login(world["coordinator"])
    page = client.get(page_url(world)).content.decode()
    assert "Docente T1" in page and "abaixo do mínimo" in page


def test_the_page_shows_a_dash_for_a_unit_without_teacher(client, world):
    """Nobody yet."""
    client.force_login(world["coordinator"])
    row = next(
        r for r in client.get(page_url(world)).context["rows"] if r["unit"].pk == unit(world).pk
    )
    assert row["unit"].teacher is None and row["teacher_load"] is None


def test_the_page_offers_to_give_or_change_the_teacher_to_who_can_write(client, world):
    """'Atribuir docente' when there is none, 'Mudar ou retirar docente' when there is."""
    open_cell(world)
    client.force_login(world["coordinator"])
    assert "Atribuir docente" in client.get(page_url(world)).content.decode()
    assign_teacher(world["coordinator"], unit(world), world["mine"])
    page = client.get(page_url(world)).content.decode()
    assert "Mudar ou retirar docente" in page and teacher_url(world) in page


def test_the_page_has_no_teacher_buttons_without_write_access(client, world):
    """Not opened for the coordinator: nothing to press."""
    client.force_login(world["coordinator"])
    assert teacher_url(world) not in client.get(page_url(world)).content.decode()


# --- the form ----------------------------------------------------------------------------------


def test_the_form_offers_only_active_teachers_of_the_coordination_with_their_load(client, world):
    """Not the other coordination's teachers, not the inactive ones; each with the annual load."""
    open_cell(world)
    client.force_login(world["coordinator"])
    form = client.get(teacher_url(world)).context["form"]
    assert set(form.fields["teacher"].queryset) == {world["mine"], world["mine2"]}
    labels = [label for _, label in form.fields["teacher"].choices if label != "---------"]
    assert any("Docente T1" in label and "abaixo do mínimo" in label for label in labels)


def test_the_coordinator_gives_a_teacher_from_the_form(client, world):
    """Posting the teacher and the version the user saw."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = post(client, world, world["mine"])
    assert response.status_code == 302 and response["Location"] == page_url(world)
    assert unit(world).teacher == world["mine"]


def test_changing_without_a_reason_shows_an_error(client, world):
    """The form asks for the reason once the unit has a teacher."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit(world), world["mine"])
    client.force_login(world["coordinator"])
    assert post(client, world, world["mine2"]).status_code == 200
    assert unit(world).teacher == world["mine"]


def test_choosing_nobody_with_a_reason_takes_the_teacher_off(client, world):
    """The empty choice removes the teacher."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit(world), world["mine"])
    client.force_login(world["coordinator"])
    assert post(client, world, None, reason="leaves").status_code == 302
    assert unit(world).teacher is None


def test_choosing_nobody_without_a_reason_shows_an_error(client, world):
    """Removing needs a reason too."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit(world), world["mine"])
    client.force_login(world["coordinator"])
    assert post(client, world, None).status_code == 200
    assert unit(world).teacher == world["mine"]


def test_a_stale_form_shows_the_message(client, world):
    """The unit changed after the form was loaded."""
    open_cell(world)
    seen = unit(world).version
    assign_teacher(world["manager"], unit(world), world["mine"])
    client.force_login(world["coordinator"])
    response = post(client, world, world["mine2"], reason="x", seen=seen)
    assert response.status_code == 200
    assert "alterado por outra pessoa" in response.content.decode()


def test_the_state_error_is_shown_on_the_form(client, world):
    """Before the opening the coordinator gets the message and nothing is saved."""
    client.force_login(world["coordinator"])
    response = post(client, world, world["mine"])
    assert response.status_code == 200 and "ainda não foi aberto" in response.content.decode()
    assert unit(world).teacher is None


@pytest.mark.parametrize("who", ["other", "teacher_user"])
def test_others_get_403_on_the_teacher_form(client, world, who):
    """Same permission as the other assignments."""
    open_cell(world)
    client.force_login(world[who])
    assert client.get(teacher_url(world)).status_code == 403
    assert post(client, world, world["mine"]).status_code == 403
    assert unit(world).teacher is None


def test_a_unit_of_another_offering_in_the_url_is_not_found(client, world):
    """The unit must belong to the offering in the URL."""
    open_cell(world)
    other = Subject.objects.create(
        study_plan=world["offering"].subject.study_plan,
        code="A2",
        name="Disciplina A2",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=world["coordination"],
        semester_hours=Decimal("75"),
    )
    SubjectClassLoad.objects.create(subject=other, class_type=world["T"], weekly_hours="2")
    generate_offerings(world["manager"], [world["semester"]])
    foreign = TeachingUnit.objects.filter(offering__subject=other).first()
    client.force_login(world["coordinator"])
    url = reverse("dsd:unit_teacher", args=[world["offering"].pk, foreign.pk])
    assert client.get(url).status_code == 404


def test_anonymous_visitors_are_redirected_to_login(client, world):
    """The form requires a session."""
    response = client.get(teacher_url(world))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_the_teacher_form_is_guarded_by_the_assignment_action():
    """It uses ``dsd.assignment.edit``, not the unit edit, so they can differ in phase 3."""
    from apps.dsd.views import UnitRoomView, UnitTeacherView

    assert UnitTeacherView.permission_code == "dsd.assignment.edit"
    assert UnitRoomView.permission_code == "dsd.teaching_unit.edit"


# --- the review findings -----------------------------------------------------------------------


def labels(client, world):
    """The texts of the teacher choices of the form."""
    form = client.get(teacher_url(world)).context["form"]
    return [label for _, label in form.fields["teacher"].choices if label != "---------"]


def test_the_labels_show_the_load_each_candidate_would_have_with_this_unit(client, world):
    """Ana has 5 h (below the minimum of 6); with the 2 h of this unit she would have 7."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit(world, "P"), world["mine"])  # 3 h
    client.force_login(world["coordinator"])
    # The T unit (2 h) has no teacher: Docente T1 has 3 h now and would have 5; T2 would have 2.
    found = {label.split(" – ")[0]: label for label in labels(client, world)}
    assert "5.00 h" in found["Docente T1"]
    assert "2.00 h" in found["Docente T2"]


def test_the_current_teacher_is_shown_with_the_load_they_have(client, world):
    """The teacher of this very unit already counts it: no hours are added again."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit(world, "T"), world["mine"])  # 2 h
    client.force_login(world["coordinator"])
    found = {label.split(" – ")[0]: label for label in labels(client, world)}
    assert "2.00 h" in found["Docente T1"]


def test_a_deactivated_current_teacher_stays_among_the_choices_and_is_marked(client, world):
    """Otherwise the form would look like 'Sem docente' and saving would remove them."""
    open_cell(world)
    assign_teacher(world["coordinator"], unit(world), world["mine"])
    Teacher.objects.filter(pk=world["mine"].pk).update(is_active=False)
    client.force_login(world["coordinator"])
    form = client.get(teacher_url(world)).context["form"]
    assert form.initial["teacher"] == world["mine"].pk
    assert world["mine"] in form.fields["teacher"].queryset
    assert any("inativo" in label for label in labels(client, world))


def test_a_post_without_the_version_is_refused(client, world):
    """The version of the unit is part of the form: without it there is no lock to check."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = client.post(teacher_url(world), {"teacher": world["mine"].pk, "reason": ""})
    assert response.status_code == 200 and unit(world).teacher is None
