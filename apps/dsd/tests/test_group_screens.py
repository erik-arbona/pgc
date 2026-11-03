"""Tests for the screens that divide a turma into groups (T3.2b).

Implements: docs/backlog_fase2.md T3.2; D90 (groups), D86 (state of the cell: the buttons only
show to who can write), D81 (sizes, provisional while estimated), D54 (versions the user saw).
"""

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
from apps.dsd.lifecycle import cell_writable
from apps.dsd.models import Offering, OfferingClassGroup, SubGroup, TeachingUnit
from apps.dsd.services import change_state, create_dsd, generate_offerings, set_group_count

pytestmark = pytest.mark.django_db


def user_with(django_user_model, profile, kind, scope_id, username):
    """A user with one role."""
    user = django_user_model.objects.create_user(username=username, password="x")
    RoleAssignment.objects.create(user=user, profile=profile, scope_kind=kind, scope_id=scope_id)
    return user


@pytest.fixture
def world(django_user_model):
    """A DSD of 2026 with turma A and a subject with T and P, generated; roles of both sides."""
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
    dsd = create_dsd(years[2026], manager)
    semester = dsd.semesters.get(number=1)
    generate_offerings(manager, [semester])
    return {
        "manager": manager,
        "coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, coordination.pk, "c"
        ),
        "other_coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, other.pk, "o"
        ),
        "teacher": user_with(django_user_model, Profile.TEACHER, ScopeKind.NONE, None, "t"),
        "semester": semester,
        "coordination": coordination,
        "turma": turma,
        "years": years,
        "offering": Offering.objects.get(),
        "link": OfferingClassGroup.objects.get(),
        "P": ClassType.objects.get(code="P"),
        "T": ClassType.objects.get(code="T"),
    }


def open_cell(world):
    """Open the semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def form_url(world, class_type="P"):
    """The form to divide the turma for a class type."""
    return reverse(
        "dsd:offering_groups", args=[world["offering"].pk, world["link"].pk, world[class_type].pk]
    )


def page_url(world):
    """The page of the offering."""
    return reverse("dsd:offering_detail", args=[world["offering"].pk])


def versions(world, class_type="P"):
    """The ``seen`` field the form carries: unit id and version pairs."""
    return ",".join(
        f"{u.pk}:{u.version}"
        for u in TeachingUnit.objects.filter(
            offering=world["offering"], class_type=world[class_type]
        )
    )


def post(client, world, n, reason="", seen=None, class_type="P"):
    """Post the form."""
    return client.post(
        form_url(world, class_type),
        {
            "groups": n,
            "reason": reason,
            "seen": versions(world, class_type) if seen is None else seen,
        },
    )


# --- cell_writable -----------------------------------------------------------------------------


def test_cell_writable_follows_the_state_and_the_role(world):
    """Open: both; not opened: only the manager; closed: nobody; other coordinators never."""
    args = ("dsd.teaching_unit.edit", world["semester"], world["coordination"].pk)
    assert cell_writable(world["manager"], *args)
    assert not cell_writable(world["coordinator"], *args)
    assert not cell_writable(world["teacher"], *args)
    open_cell(world)
    assert cell_writable(world["manager"], *args) and cell_writable(world["coordinator"], *args)
    assert not cell_writable(world["other_coordinator"], *args)
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="done"
    )
    assert not cell_writable(world["manager"], *args)
    assert not cell_writable(world["coordinator"], *args)


# --- the form ----------------------------------------------------------------------------------


def test_the_form_starts_with_the_current_number_of_groups(client, world):
    """One group (the whole turma) before dividing."""
    open_cell(world)
    client.force_login(world["coordinator"])
    assert client.get(form_url(world)).context["form"].initial["groups"] == 1


def test_the_form_of_a_divided_turma_starts_with_its_number_of_groups(client, world):
    """Three groups now: the form starts at 3 and carries the versions of the three units."""
    open_cell(world)
    set_group_count(world["manager"], world["link"], world["P"], 3)
    client.force_login(world["coordinator"])
    form = client.get(form_url(world)).context["form"]
    assert form.initial["groups"] == 3
    assert form.initial["seen"] == versions(world)


def test_the_form_shows_the_turma_size_and_the_average_per_group(client, world):
    """A guide only: the size and size / N, provisional while estimated (Q6, D81)."""
    open_cell(world)
    Enrollment.objects.create(
        class_group=world["turma"],
        academic_year=world["years"][2026],
        kind="estimated",
        students=31,
    )
    client.force_login(world["coordinator"])
    page = client.get(form_url(world)).content.decode()
    assert "31" in page and "provisório" in page


def test_the_coordinator_divides_the_turma_from_the_form(client, world):
    """Posting N = 3 creates the three groups and goes back to the page."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = post(client, world, 3)
    assert response.status_code == 302 and response["Location"] == page_url(world)
    assert SubGroup.objects.filter(class_group_link=world["link"]).count() == 3


def test_changing_without_a_reason_shows_an_error_and_keeps_the_groups(client, world):
    """The reason is required once the turma is divided."""
    open_cell(world)
    client.force_login(world["coordinator"])
    post(client, world, 3)
    response = post(client, world, 2)
    assert response.status_code == 200
    assert SubGroup.objects.filter(class_group_link=world["link"]).count() == 3


def test_changing_with_a_reason_works(client, world):
    """Going down to 2 with a reason deletes the third group."""
    open_cell(world)
    client.force_login(world["coordinator"])
    post(client, world, 3)
    assert post(client, world, 2, reason="fewer labs").status_code == 302
    assert SubGroup.objects.filter(class_group_link=world["link"]).count() == 2


def test_a_form_that_saw_old_units_is_refused_with_a_message(client, world):
    """Someone else divided the turma after the form was loaded (D54)."""
    open_cell(world)
    seen = versions(world)
    set_group_count(world["manager"], world["link"], world["P"], 2)
    client.force_login(world["coordinator"])
    response = post(client, world, 3, reason="x", seen=seen)
    assert response.status_code == 200
    assert "alterado por outra pessoa" in response.content.decode()
    assert SubGroup.objects.filter(class_group_link=world["link"]).count() == 2


def test_the_state_error_is_shown_on_the_form(client, world):
    """Before the opening the coordinator gets the message and nothing is created."""
    client.force_login(world["coordinator"])
    response = post(client, world, 2)
    assert response.status_code == 200 and "ainda não foi aberto" in response.content.decode()
    assert not SubGroup.objects.exists()


def test_the_number_is_limited_on_the_form(client, world):
    """0 and 21 show an error and create nothing."""
    open_cell(world)
    client.force_login(world["coordinator"])
    for n in (0, 21):
        assert post(client, world, n).status_code == 200
    assert not SubGroup.objects.exists()


@pytest.mark.parametrize("who", ["other_coordinator", "teacher"])
def test_others_get_403_on_the_form(client, world, who):
    """Not the coordinator of the coordination, not the manager of the Faculty."""
    open_cell(world)
    client.force_login(world[who])
    assert client.get(form_url(world)).status_code == 403
    assert post(client, world, 2).status_code == 403
    assert not SubGroup.objects.exists()


def test_a_link_of_another_offering_is_not_found(client, world):
    """The turma link in the URL must belong to the offering in the URL."""
    open_cell(world)
    client.force_login(world["manager"])
    bad = reverse(
        "dsd:offering_groups", args=[world["offering"].pk, world["link"].pk + 999, world["P"].pk]
    )
    assert client.get(bad).status_code == 404


def test_a_link_that_belongs_to_another_offering_is_not_found(client, world):
    """A real turma link, but of a different offering than the one in the URL."""
    second = Subject.objects.create(
        study_plan=world["turma"].study_plan,
        code="A2",
        name="Disciplina A2",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=world["coordination"],
        semester_hours=Decimal("75"),
    )
    SubjectClassLoad.objects.create(subject=second, class_type=world["P"], weekly_hours="2")
    generate_offerings(world["manager"], [world["semester"]])
    foreign = OfferingClassGroup.objects.get(offering__subject=second)
    client.force_login(world["manager"])
    url = reverse("dsd:offering_groups", args=[world["offering"].pk, foreign.pk, world["P"].pk])
    assert client.get(url).status_code == 404


def test_anonymous_visitors_are_redirected_to_login(client, world):
    """The form requires a session."""
    response = client.get(form_url(world))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


# --- the buttons on the page -------------------------------------------------------------------


def test_the_page_offers_to_divide_a_whole_turma_to_who_can_write(client, world):
    """The coordinator sees the button in an open cell, for each class type."""
    open_cell(world)
    client.force_login(world["coordinator"])
    page = client.get(page_url(world)).content.decode()
    assert form_url(world, "P") in page and form_url(world, "T") in page
    assert "Dividir em grupos" in page


def test_the_page_has_no_buttons_when_the_cell_is_not_opened_for_the_coordinator(client, world):
    """Not opened: the coordinator cannot write, so no buttons; the manager has them."""
    client.force_login(world["coordinator"])
    assert form_url(world) not in client.get(page_url(world)).content.decode()
    client.force_login(world["manager"])
    assert form_url(world) in client.get(page_url(world)).content.decode()


def test_the_page_has_no_buttons_in_a_closed_cell_or_for_other_coordinators(client, world):
    """Closed: nobody. Another coordination's coordinator: never."""
    open_cell(world)
    client.force_login(world["other_coordinator"])
    assert form_url(world) not in client.get(page_url(world)).content.decode()
    change_state(
        world["manager"], "close", [world["semester"]], [world["coordination"]], reason="done"
    )
    for who in ("manager", "coordinator"):
        client.force_login(world[who])
        assert form_url(world) not in client.get(page_url(world)).content.decode()


def test_a_divided_turma_shows_its_groups_and_one_button_to_change_them(client, world):
    """Three group rows, labelled by turma, type and number, and a single 'change' button."""
    open_cell(world)
    set_group_count(world["manager"], world["link"], world["P"], 3)
    client.force_login(world["coordinator"])
    page = client.get(page_url(world)).content.decode()
    assert "A – P1" in page and "A – P2" in page and "A – P3" in page
    assert page.count(form_url(world, "P")) == 1
    assert "Alterar n.º de grupos" in page
