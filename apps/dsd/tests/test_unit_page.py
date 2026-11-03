"""Tests for the read-only page of an offering with its teaching units (T3.1b).

Implements: docs/backlog_fase2.md T3.1; D89 (units), D69 (manager and coordinator read
everything), D81 (sizes, provisional while estimated).
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
from apps.dsd.models import Offering, TeachingUnit, TeachingUnitMember
from apps.dsd.services import create_dsd, generate_offerings, stale_unit_ids

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    """A DSD of 2026 with one turma, one subject with T (2 h) and TP (3 h), generated."""
    faculty = Faculty.objects.create(name="Faculdade A", code="FA")
    coordination = Coordination.objects.create(faculty=faculty, name="Coordenação A")
    years = {y: AcademicYear.objects.create(start_year=y) for y in (2023, 2025, 2026)}
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="EIC", level="bachelor"),
        academic_year=years[2023],
    )
    manager = django_user_model.objects.create_user(username="m", password="x")
    RoleAssignment.objects.create(
        user=manager, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.FACULTY, scope_id=faculty.pk
    )
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
    for code, hours in (("T", "2"), ("TP", "3")):
        SubjectClassLoad.objects.create(
            subject=subject, class_type=ClassType.objects.get(code=code), weekly_hours=hours
        )
    dsd = create_dsd(years[2026], manager)
    semester = dsd.semesters.get(number=1)
    generate_offerings(manager, [semester])
    return {
        "manager": manager,
        "turma": turma,
        "subject": subject,
        "years": years,
        "semester": semester,
        "coordination": coordination,
        "offering": Offering.objects.get(),
    }


def url(world):
    """The page of the offering."""
    return reverse("dsd:offering_detail", args=[world["offering"].pk])


# --- who sees it -------------------------------------------------------------------------------


def test_anonymous_visitors_are_redirected_to_login(client, world):
    """The page requires a session."""
    response = client.get(url(world))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [Profile.PGC_MANAGER, Profile.COORDINATOR])
def test_manager_and_coordinator_read_it(client, make_user, world, profile):
    """Both see every offering, whatever their coordination (D69)."""
    client.force_login(make_user(profile, f"u-{profile}"))
    assert client.get(url(world)).status_code == 200


@pytest.mark.parametrize(
    "profile", [p for p in Profile if p not in (Profile.PGC_MANAGER, Profile.COORDINATOR)]
)
def test_other_profiles_get_403(client, make_user, world, profile):
    """Board, teacher, viewer and the others do not read it."""
    client.force_login(make_user(profile))
    assert client.get(url(world)).status_code == 403


def test_an_unknown_offering_is_a_404_for_who_may_read(client, world):
    """Nothing to show: 404, only after the permission check."""
    client.force_login(world["manager"])
    assert (
        client.get(reverse("dsd:offering_detail", args=[world["offering"].pk + 999])).status_code
        == 404
    )


# --- what it shows -----------------------------------------------------------------------------


def test_it_lists_one_row_per_unit_with_type_hours_and_turmas(client, world):
    """T with 2 h and TP with 3 h, each for turma A."""
    client.force_login(world["manager"])
    rows = client.get(url(world)).context["rows"]
    assert [(r["unit"].class_type.code, r["weekly_hours"]) for r in rows] == [
        ("T", Decimal("2.00")),
        ("TP", Decimal("3.00")),
    ]
    assert all(r["groups"] == [world["turma"]] for r in rows)


def test_the_size_is_the_sum_of_the_turmas_and_provisional_while_estimated(client, world):
    """An estimate counts, marked provisional; the real number replaces it (D81)."""
    Enrollment.objects.create(
        class_group=world["turma"],
        academic_year=world["years"][2026],
        kind="estimated",
        students=31,
    )
    client.force_login(world["manager"])
    page = client.get(url(world)).content.decode()
    assert "31" in page and "provisório" in page
    Enrollment.objects.create(
        class_group=world["turma"], academic_year=world["years"][2026], kind="actual", students=28
    )
    page = client.get(url(world)).content.decode()
    assert "28" in page and "provisório" not in page


def test_the_size_of_a_merged_unit_adds_up_its_turmas(client, world):
    """When a unit has several turmas (a merge, T3.3), the page shows the sum of their sizes."""
    other = ClassGroup.objects.create(
        course=world["turma"].course,
        intake_year=world["years"][2026],
        study_plan=world["turma"].study_plan,
        label="B",
    )
    generate_offerings(world["manager"], [world["semester"]])
    own = TeachingUnit.objects.get(
        class_type__code="T", members__class_group_link__class_group=other
    )
    host = TeachingUnit.objects.get(
        class_type__code="T", members__class_group_link__class_group=world["turma"]
    )
    link = own.members.get().class_group_link
    TeachingUnit.objects.filter(pk=own.pk).delete()  # a queryset skips the write guard
    TeachingUnitMember.objects.bulk_create(
        [TeachingUnitMember(unit=host, class_group_link=link, class_type=host.class_type)]
    )
    for turma, students in ((world["turma"], 31), (other, 20)):
        Enrollment.objects.create(
            class_group=turma, academic_year=world["years"][2026], kind="actual", students=students
        )
    client.force_login(world["manager"])
    rows = {r["unit"].pk: r for r in client.get(url(world)).context["rows"]}
    assert rows[host.pk]["students"] == 51 and rows[host.pk]["groups"] == [world["turma"], other]


def test_a_turma_without_a_number_says_so(client, world):
    """The unit is listed with 'sem matrícula'."""
    client.force_login(world["manager"])
    assert "sem matrícula" in client.get(url(world)).content.decode()


def test_the_page_names_the_subject_semester_and_regente_label(client, world):
    """The header says which subject and semester this is, and the regente (a dash if none)."""
    client.force_login(world["manager"])
    page = client.get(url(world)).content.decode()
    assert "A1 – Disciplina A1" in page and "2026-2027" in page and "Regente: —" in page


def test_a_stale_unit_is_flagged(client, world):
    """The load of TP is removed: its unit stays and the page marks it as obsolete."""
    SubjectClassLoad.objects.filter(subject=world["subject"], class_type__code="TP").delete()
    client.force_login(world["manager"])
    response = client.get(url(world))
    flags = {r["unit"].class_type.code: r["stale"] for r in response.context["rows"]}
    assert flags == {"T": False, "TP": True}
    assert "obsoleta" in response.content.decode().lower()


def test_a_stale_unit_has_no_hours(client, world):
    """A class type that left the subject's loads has no weekly hours any more."""
    SubjectClassLoad.objects.filter(subject=world["subject"], class_type__code="TP").delete()
    client.force_login(world["manager"])
    rows = {
        r["unit"].class_type.code: r["weekly_hours"] for r in client.get(url(world)).context["rows"]
    }
    assert rows == {"T": Decimal("2.00"), "TP": None}


# --- the service and the list ------------------------------------------------------------------


def test_stale_unit_ids_agrees_with_the_generation_count(world):
    """The page and the generation message count the same units."""
    SubjectClassLoad.objects.filter(subject=world["subject"], class_type__code="TP").delete()
    stale = stale_unit_ids(world["semester"], world["coordination"].pk)
    assert stale == {TeachingUnit.objects.get(class_type__code="TP").pk}
    assert generate_offerings(world["manager"], [world["semester"]]).stale_units == len(stale)


def test_the_offerings_list_shows_the_units_count_and_links_to_the_page(client, world):
    """One link per offering, with the number of units."""
    client.force_login(world["manager"])
    list_url = reverse("dsd:offering_list", args=[world["semester"].dsd_id])
    page = client.get(list_url).content.decode()
    assert url(world) in page
    assert client.get(list_url).context["rows"][0][0].teaching_units.count() == 2
