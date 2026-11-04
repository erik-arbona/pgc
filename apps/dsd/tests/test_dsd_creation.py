"""Tests for creating the DSD of an academic year (T2.1).

Implements: docs/backlog_fase2.md T2.1 and D43 – only the PGC manager creates the DSD, one per
academic year (guaranteed by the database), with the two semesters created together.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.academic.models import AcademicYear
from apps.core.models import AuditEntry, Profile
from apps.dsd.models import Dsd, DsdSemester
from apps.dsd.services import create_dsd

pytestmark = pytest.mark.django_db


@pytest.fixture
def year():
    """The academic year 2026-2027."""
    return AcademicYear.objects.create(start_year=2026)


@pytest.fixture
def actor():
    """A user who creates the DSD."""
    return get_user_model().objects.create_user(username="actor", password="x")


# --- the model ---------------------------------------------------------------------------------


def test_a_second_dsd_for_the_same_year_is_refused_by_the_database(year):
    """One DSD per academic year is a database guarantee (D43)."""
    Dsd.objects.create(academic_year=year)
    with pytest.raises(IntegrityError), transaction.atomic():
        Dsd.objects.create(academic_year=year)


def test_a_semester_number_must_be_one_or_two(year):
    """The DSD has two semesters; a third one cannot exist."""
    dsd = Dsd.objects.create(academic_year=year)
    with pytest.raises(IntegrityError), transaction.atomic():
        DsdSemester.objects.create(dsd=dsd, number=3)


def test_a_semester_number_is_unique_inside_a_dsd(year):
    """The same semester cannot be created twice in a DSD."""
    dsd = Dsd.objects.create(academic_year=year)
    DsdSemester.objects.create(dsd=dsd, number=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        DsdSemester.objects.create(dsd=dsd, number=1)


def test_the_academic_year_of_a_dsd_cannot_be_deleted(year):
    """A year that has a DSD is protected from deletion."""
    from django.db.models import ProtectedError

    Dsd.objects.create(academic_year=year)
    with pytest.raises(ProtectedError):
        year.delete()


# --- the service -------------------------------------------------------------------------------


def test_creating_a_dsd_creates_its_two_semesters(year, actor):
    """The DSD comes with the 1st and the 2nd semester."""
    dsd = create_dsd(year, actor)
    assert dsd.academic_year == year
    assert sorted(dsd.semesters.values_list("number", flat=True)) == [1, 2]


def test_creating_a_dsd_is_audited_with_the_semesters(year, actor):
    """One audit entry for the DSD and one for each semester, with the actor and the reason."""
    dsd = create_dsd(year, actor, reason="start of the year")
    entries = AuditEntry.objects.filter(actor=actor)
    assert entries.filter(entity="dsd.dsd", entity_id=str(dsd.pk)).count() == 1
    assert entries.filter(entity="dsd.dsdsemester").count() == 2
    assert entries.filter(entity="dsd.dsd").get().reason == "start of the year"


def test_a_second_dsd_for_the_year_is_refused_with_a_clear_message(year, actor):
    """The second attempt says that a DSD already exists for that year."""
    create_dsd(year, actor)
    with pytest.raises(ValidationError) as error:
        create_dsd(year, actor)
    assert "2026-2027" in error.value.messages[0]
    assert "Já existe um DSD" in error.value.messages[0]
    assert Dsd.objects.count() == 1 and DsdSemester.objects.count() == 2


def test_losing_the_race_gives_the_same_clear_message(year, actor, monkeypatch):
    """If another manager creates it between the check and the save, the message is the same.

    The existence check is patched away so that the save itself hits the database constraint,
    which is what happens with two simultaneous requests.
    """
    create_dsd(year, actor)
    monkeypatch.setattr("apps.dsd.services._existing_dsd", lambda academic_year: None)
    with pytest.raises(ValidationError) as error:
        create_dsd(year, actor)
    assert "Já existe um DSD" in error.value.messages[0]
    assert Dsd.objects.count() == 1 and DsdSemester.objects.count() == 2


# --- the screens -------------------------------------------------------------------------------

LIST_URL = "dsd:dsd_list"
CREATE_URL = "dsd:dsd_create"


def test_anonymous_visitors_are_redirected_to_login(client):
    """Both screens require a session."""
    for name in (LIST_URL, CREATE_URL):
        response = client.get(reverse(name))
        assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_the_manager_creates_the_dsd_of_a_year(client, make_user, year):
    """Posting the form creates the DSD and goes back to the list."""
    client.force_login(make_user(Profile.PGC_MANAGER))
    response = client.post(reverse(CREATE_URL), {"academic_year": year.pk})
    assert response.status_code == 302
    assert Dsd.objects.get().academic_year == year
    assert DsdSemester.objects.count() == 2


def test_a_second_creation_shows_the_message_on_the_form(client, make_user, year):
    """The form is shown again with the clear message and nothing is created."""
    client.force_login(make_user(Profile.PGC_MANAGER))
    client.post(reverse(CREATE_URL), {"academic_year": year.pk})
    response = client.post(reverse(CREATE_URL), {"academic_year": year.pk})
    assert response.status_code == 200
    assert "Já existe um DSD" in response.content.decode()
    assert Dsd.objects.count() == 1


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_only_the_manager_creates(client, make_user, year, profile):
    """Coordinator, board, teacher and the others cannot create the DSD (D43)."""
    client.force_login(make_user(profile))
    assert client.get(reverse(CREATE_URL)).status_code == 403
    assert client.post(reverse(CREATE_URL), {"academic_year": year.pk}).status_code == 403
    assert not Dsd.objects.exists()


@pytest.mark.parametrize("profile", [Profile.PGC_MANAGER, Profile.COORDINATOR])
def test_manager_and_coordinator_read_the_list(client, make_user, year, profile):
    """Both see the DSDs that exist."""
    dsd = Dsd.objects.create(academic_year=year)
    client.force_login(make_user(profile))
    response = client.get(reverse(LIST_URL))
    assert response.status_code == 200
    assert list(response.context["object_list"]) == [dsd]


@pytest.mark.parametrize(
    "profile", [p for p in Profile if p not in (Profile.PGC_MANAGER, Profile.COORDINATOR)]
)
def test_other_profiles_do_not_read_the_list(client, make_user, profile):
    """The other profiles get 403 on the list."""
    client.force_login(make_user(profile))
    assert client.get(reverse(LIST_URL)).status_code == 403


def test_the_coordinator_does_not_see_the_create_link(client, make_user, year):
    """The list offers the creation only to who can do it."""
    client.force_login(make_user(Profile.COORDINATOR))
    assert reverse(CREATE_URL) not in client.get(reverse(LIST_URL)).content.decode()
    client.logout()
    client.force_login(make_user(Profile.PGC_MANAGER, "m"))
    assert reverse(CREATE_URL) in client.get(reverse(LIST_URL)).content.decode()
