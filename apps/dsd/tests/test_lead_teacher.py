"""Tests for the regente (lead teacher) of an offering (T2.3b).

Implements: docs/backlog_fase2.md T2.3; D69 (a coordination only distributes its own teachers),
D86 (state of the cell), D87 (offerings), D40 (reason), D54 (optimistic lock).
"""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
)
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.dsd.models import Offering
from apps.dsd.services import change_state, create_dsd, generate_offerings, set_lead_teacher
from apps.staff.models import Category, Teacher

pytestmark = pytest.mark.django_db


def teacher(coordination, identifier, active=True):
    """A teacher of a coordination."""
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
    """A DSD with one offering of coordination A, a manager, two coordinators and teachers."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coord_a = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    coord_b = Coordination.objects.create(faculty=faculty, name="Coordenação B")
    year = AcademicYear.objects.create(start_year=2026)
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="EIC", level="bachelor"),
        academic_year=year,
    )
    ClassGroup.objects.create(course=plan.course, intake_year=year, study_plan=plan)
    Subject.objects.create(
        study_plan=plan,
        code="A1",
        name="Disciplina A1",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=coord_a,
        semester_hours=Decimal("75"),
    )
    manager = user_with(django_user_model, Profile.PGC_MANAGER, ScopeKind.FACULTY, faculty.pk, "m")
    dsd = create_dsd(year, manager)
    semester = dsd.semesters.get(number=1)
    generate_offerings(manager, [semester])
    return {
        "manager": manager,
        "coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, coord_a.pk, "ca"
        ),
        "other_coordinator": user_with(
            django_user_model, Profile.COORDINATOR, ScopeKind.COORDINATION, coord_b.pk, "cb"
        ),
        "semester": semester,
        "coord_a": coord_a,
        "coord_b": coord_b,
        "offering": Offering.objects.get(),
        "mine": teacher(coord_a, "T1"),
        "other_mine": teacher(coord_a, "T2"),
        "foreign": teacher(coord_b, "T3"),
        "inactive": teacher(coord_a, "T4", active=False),
    }


def open_cell(world):
    """Open the semester for coordination A."""
    change_state(world["manager"], "open", [world["semester"]], [world["coord_a"]])


def current(world):
    """The offering as stored."""
    return Offering.objects.get(pk=world["offering"].pk)


# --- the service -------------------------------------------------------------------------------


def test_the_coordinator_sets_the_regente_of_an_open_cell(world):
    """A teacher of the coordination, without a reason the first time."""
    open_cell(world)
    set_lead_teacher(world["coordinator"], current(world), world["mine"])
    assert current(world).lead_teacher == world["mine"]


def test_the_manager_sets_it_before_the_cell_is_opened(world):
    """The manager prepares the offerings before opening the semester (D86)."""
    set_lead_teacher(world["manager"], current(world), world["mine"])
    assert current(world).lead_teacher == world["mine"]


def test_the_coordinator_cannot_set_it_before_the_cell_is_opened(world):
    """Not opened means the coordinator does not write yet."""
    with pytest.raises(ValidationError):
        set_lead_teacher(world["coordinator"], current(world), world["mine"])
    assert current(world).lead_teacher is None


def test_nobody_sets_it_in_a_closed_cell(world):
    """Closed is read-only, also for the manager."""
    open_cell(world)
    change_state(world["manager"], "close", [world["semester"]], [world["coord_a"]], reason="done")
    for who in ("coordinator", "manager"):
        with pytest.raises(ValidationError) as error:
            set_lead_teacher(world[who], current(world), world["mine"], reason="x")
        assert "fechado" in error.value.messages[0]
    assert current(world).lead_teacher is None


def test_a_teacher_of_another_coordination_is_refused(world):
    """The regente belongs to the coordination of the subject (D69)."""
    open_cell(world)
    with pytest.raises(ValidationError):
        set_lead_teacher(world["coordinator"], current(world), world["foreign"])
    assert current(world).lead_teacher is None


def test_an_inactive_teacher_is_refused(world):
    """An inactive teacher cannot be the regente."""
    open_cell(world)
    with pytest.raises(ValidationError):
        set_lead_teacher(world["coordinator"], current(world), world["inactive"])


def test_a_coordinator_of_another_coordination_is_denied(world):
    """The scope of the coordination is checked, whatever the state."""
    open_cell(world)
    with pytest.raises(PermissionDenied):
        set_lead_teacher(world["other_coordinator"], current(world), world["mine"])
    assert current(world).lead_teacher is None


def test_changing_the_regente_needs_a_reason(world):
    """The first time no reason; changing it afterwards needs one (D40)."""
    open_cell(world)
    set_lead_teacher(world["coordinator"], current(world), world["mine"])
    with pytest.raises(ValidationError):
        set_lead_teacher(world["coordinator"], current(world), world["other_mine"], reason=" ")
    assert current(world).lead_teacher == world["mine"]
    set_lead_teacher(world["coordinator"], current(world), world["other_mine"], reason="swap")
    assert current(world).lead_teacher == world["other_mine"]


def test_removing_the_regente_needs_a_reason(world):
    """Clearing it is a change as well."""
    open_cell(world)
    set_lead_teacher(world["coordinator"], current(world), world["mine"])
    with pytest.raises(ValidationError):
        set_lead_teacher(world["coordinator"], current(world), None)
    set_lead_teacher(world["coordinator"], current(world), None, reason="left the course")
    assert current(world).lead_teacher is None


def test_setting_the_same_teacher_writes_nothing(world):
    """No change, no version bump and no audit entry."""
    open_cell(world)
    set_lead_teacher(world["coordinator"], current(world), world["mine"])
    before = (current(world).version, AuditEntry.objects.count())
    set_lead_teacher(world["coordinator"], current(world), world["mine"])
    assert (current(world).version, AuditEntry.objects.count()) == before


def test_a_stale_version_is_refused(world):
    """Someone else saved the offering after this copy was loaded (D54)."""
    open_cell(world)
    stale = current(world)
    set_lead_teacher(world["manager"], current(world), world["other_mine"])
    with pytest.raises(ValidationError) as error:
        set_lead_teacher(world["coordinator"], stale, world["mine"], reason="x")
    assert "alterado por outra pessoa" in error.value.messages[0]
    assert current(world).lead_teacher == world["other_mine"]


def test_the_change_is_audited_with_the_old_and_new_regente(world):
    """Who, when, old value, new value and why."""
    open_cell(world)
    set_lead_teacher(world["coordinator"], current(world), world["mine"])
    set_lead_teacher(world["coordinator"], current(world), world["other_mine"], reason="swap")
    entry = AuditEntry.objects.filter(entity="dsd.offering", action="update").latest("pk")
    assert entry.actor == world["coordinator"] and entry.reason == "swap"
    assert entry.old_value["lead_teacher"] == world["mine"].pk
    assert entry.new_value["lead_teacher"] == world["other_mine"].pk


# --- the screen --------------------------------------------------------------------------------


def url(world):
    """The regente form of the offering."""
    return reverse("dsd:offering_lead_teacher", args=[world["offering"].pk])


def test_the_form_offers_only_active_teachers_of_the_coordination(client, world):
    """Not the other coordination's teachers, not the inactive ones."""
    open_cell(world)
    client.force_login(world["coordinator"])
    choices = client.get(url(world)).context["form"].fields["teacher"].queryset
    assert set(choices) == {world["mine"], world["other_mine"]}


def test_the_coordinator_sets_it_from_the_form(client, world):
    """Posting the teacher and the version the user saw."""
    open_cell(world)
    client.force_login(world["coordinator"])
    response = client.post(
        url(world),
        {"teacher": world["mine"].pk, "version": current(world).version, "reason": ""},
    )
    assert response.status_code == 302 and current(world).lead_teacher == world["mine"]


def test_the_form_shows_the_state_error(client, world):
    """Before the opening the coordinator gets the message on the form and nothing is saved."""
    client.force_login(world["coordinator"])
    response = client.post(
        url(world),
        {"teacher": world["mine"].pk, "version": current(world).version, "reason": ""},
    )
    assert response.status_code == 200 and "ainda não foi aberto" in response.content.decode()
    assert current(world).lead_teacher is None


def test_the_form_asks_for_the_reason_when_changing(client, world):
    """Changing the regente without a reason shows an error and keeps the old one."""
    open_cell(world)
    set_lead_teacher(world["coordinator"], current(world), world["mine"])
    client.force_login(world["coordinator"])
    response = client.post(
        url(world),
        {"teacher": world["other_mine"].pk, "version": current(world).version, "reason": ""},
    )
    assert response.status_code == 200 and current(world).lead_teacher == world["mine"]


def test_a_stale_form_is_refused_with_a_message(client, world):
    """The version of the form is older than the stored one."""
    open_cell(world)
    seen = current(world).version
    set_lead_teacher(world["manager"], current(world), world["other_mine"])
    client.force_login(world["coordinator"])
    response = client.post(
        url(world), {"teacher": world["mine"].pk, "version": seen, "reason": "x"}
    )
    assert response.status_code == 200
    assert "alterado por outra pessoa" in response.content.decode()


def test_other_coordinators_and_profiles_get_403(client, django_user_model, world):
    """Only the coordinator of the coordination and the manager of the Faculty."""
    open_cell(world)
    others = [world["other_coordinator"]] + [
        user_with(django_user_model, profile, ScopeKind.NONE, None, f"p-{profile}")
        for profile in (Profile.VIEWER, Profile.FACILITIES)
    ]
    for user in others:
        client.force_login(user)
        assert client.get(url(world)).status_code == 403
        assert client.post(url(world), {"version": 1}).status_code == 403
    assert current(world).lead_teacher is None


def test_anonymous_visitors_are_redirected_to_login(client, world):
    """The form requires a session."""
    response = client.get(url(world))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_the_list_links_the_form_only_to_who_can_set_the_regente(client, world, dsd_url=None):
    """The 'Definir' link is for the coordinator of the coordination, not for another one."""
    list_url = reverse("dsd:offering_list", args=[world["semester"].dsd_id])
    client.force_login(world["coordinator"])
    assert url(world) in client.get(list_url).content.decode()
    client.force_login(world["other_coordinator"])
    assert url(world) not in client.get(list_url).content.decode()
