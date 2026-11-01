"""View tests for the hours range screens (T3.2, part 4).

Implements: docs/especificacao/05_dsd_regras.md – ranges with validity dates entered by the PGC
manager; D40, D46, D50, D58. A rule already in force is not edited or deleted from the screens;
the way to correct it is a newer rule.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditEntry, Profile
from apps.staff.models import Category, LoadRange, Position, Teacher

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
PAST = TODAY - timedelta(days=400)
FUTURE = TODAY + timedelta(days=400)


@pytest.fixture
def doctor():
    """The 'Doutor' category."""
    return Category.objects.get(name="Doutor")


def make_rule(**overrides):
    """Create a category rule of a teacher category."""
    data = dict(
        kind=LoadRange.Kind.CATEGORY,
        category=Category.objects.get(name="Doutor"),
        minimum_hours=Decimal("6"),
        maximum_hours=Decimal("14"),
        valid_from=FUTURE,
    )
    data.update(overrides)
    return LoadRange.objects.create(**data)


def category_data(doctor, valid_from=FUTURE, **overrides):
    """POST data for a category rule."""
    data = {
        "kind": "category",
        "category": doctor.pk,
        "position": "",
        "teacher_type": "",
        "minimum_hours": "6",
        "maximum_hours": "14",
        "valid_from": valid_from.isoformat(),
        "reason": "",
    }
    data.update(overrides)
    return data


def test_anonymous_visitors_are_redirected_to_login(client):
    """The list requires a session."""
    response = client.get(reverse("staff:loadrange_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, doctor, profile):
    """Only the PGC manager reaches the hours range screens."""
    client.force_login(make_user(profile))
    rule = make_rule()
    for name, kwargs in (
        ("list", {}),
        ("create", {}),
        ("update", {"pk": rule.pk}),
        ("delete", {"pk": rule.pk}),
    ):
        url = reverse(f"staff:loadrange_{name}", kwargs=kwargs)
        assert client.get(url).status_code == 403
        assert client.post(url, {**category_data(doctor), "reason": "x"}).status_code == 403
    assert LoadRange.objects.count() == 1
    assert not AuditEntry.objects.exists()


def test_a_superuser_without_assignment_gets_403(client):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse("staff:loadrange_list")).status_code == 403


def test_the_list_shows_the_status_of_each_rule(manager_client, doctor):
    """Rules appear as in force, superseded or future."""
    make_rule(valid_from=PAST - timedelta(days=100), maximum_hours=Decimal("16"))
    make_rule(valid_from=PAST, maximum_hours=Decimal("14"))
    make_rule(valid_from=FUTURE, maximum_hours=Decimal("12"))
    page = manager_client.get(reverse("staff:loadrange_list")).content.decode()
    assert page.count("Em vigor") == 1
    assert page.count("Substituída") == 1
    assert page.count("Futura") == 1


def test_the_list_filters_by_kind_and_returns_a_fragment_for_htmx(manager_client, doctor):
    """The kind filter narrows the list; HTMX gets only the results."""
    make_rule()
    LoadRange.objects.create(
        kind=LoadRange.Kind.TEACHER_TYPE,
        teacher_type=Teacher.Type.COMPETITION,
        maximum_hours=Decimal("18"),
        valid_from=FUTURE,
    )
    url = reverse("staff:loadrange_list")
    page = manager_client.get(url, {"kind": "teacher_type"}).content.decode()
    assert "Docente de concurso" in page and "Doutor" not in page
    fragment = manager_client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in fragment and "htmx" in manager_client.get(url).content.decode()


def test_the_create_form_starts_with_today_as_the_start_date(manager_client):
    """The start date defaults to today."""
    response = manager_client.get(reverse("staff:loadrange_create"))
    assert response.context["form"].initial["valid_from"] == TODAY


def test_creating_a_category_rule_is_audited(manager_client, doctor):
    """A new rule leaves one create entry with the actor."""
    manager_client.post(reverse("staff:loadrange_create"), category_data(doctor))
    rule = LoadRange.objects.get()
    entry = AuditEntry.objects.get()
    assert (entry.action, entry.entity_id, entry.actor.username) == (
        "create",
        str(rule.pk),
        "gestor",
    )


def test_a_type_rule_may_have_no_minimum_and_full_time_is_not_offered(manager_client):
    """A collaborator rule needs only a maximum; full-time teachers have no type rule."""
    data = {
        "kind": "teacher_type",
        "category": "",
        "position": "",
        "teacher_type": "habitual_collaborator",
        "minimum_hours": "",
        "maximum_hours": "20",
        "valid_from": FUTURE.isoformat(),
        "reason": "",
    }
    manager_client.post(reverse("staff:loadrange_create"), data)
    assert LoadRange.objects.get().maximum_hours == Decimal("20")
    response = manager_client.post(
        reverse("staff:loadrange_create"),
        {
            **data,
            "teacher_type": "full_time",
            "valid_from": (FUTURE + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 200
    assert "teacher_type" in response.context["form"].errors
    assert LoadRange.objects.count() == 1


@pytest.mark.parametrize(
    ("overrides", "text"),
    [
        ({"minimum_hours": "20", "maximum_hours": "14"}, "mínimo não pode ser superior"),
        ({"minimum_hours": ""}, "mínimo é obrigatório"),
        ({"maximum_hours": "-1", "minimum_hours": "0"}, "máximo tem de ser zero ou mais"),
    ],
)
def test_inconsistent_hours_show_a_message_in_portuguese(manager_client, doctor, overrides, text):
    """The service's messages reach the form, not a database error."""
    response = manager_client.post(
        reverse("staff:loadrange_create"), category_data(doctor, **overrides)
    )
    assert response.status_code == 200
    assert text in " ".join(response.context["form"].non_field_errors())
    assert not LoadRange.objects.exists()


def test_a_second_rule_with_the_same_start_date_is_a_form_error(manager_client, doctor):
    """The overlap is reported on the form."""
    make_rule(valid_from=FUTURE)
    response = manager_client.post(reverse("staff:loadrange_create"), category_data(doctor))
    assert response.status_code == 200
    assert "data de início" in " ".join(response.context["form"].non_field_errors())
    assert LoadRange.objects.count() == 1


def test_updating_a_future_rule_needs_a_reason_and_keeps_its_subject(manager_client, doctor):
    """The reason is required; the kind and reference cannot be changed from the form."""
    rule = make_rule()
    url = reverse("staff:loadrange_update", kwargs={"pk": rule.pk})
    data = category_data(doctor, maximum_hours="12")
    manager_client.post(url, data)
    rule.refresh_from_db()
    assert rule.maximum_hours == Decimal("14")
    attack = {**data, "reason": "Revisão", "kind": "teacher_type", "teacher_type": "competition"}
    manager_client.post(url, attack)
    rule.refresh_from_db()
    assert rule.maximum_hours == Decimal("12")
    assert (rule.kind, rule.teacher_type) == ("category", None)
    entry = AuditEntry.objects.get(action="update")
    assert entry.reason == "Revisão"


def test_a_rule_in_force_cannot_be_edited_or_deleted_from_the_screens(manager_client, doctor):
    """The user is sent back to the list with a message and nothing changes."""
    rule = make_rule(valid_from=PAST)
    for action in ("update", "delete"):
        url = reverse(f"staff:loadrange_{action}", kwargs={"pk": rule.pk})
        for response in (
            manager_client.get(url, follow=True),
            manager_client.post(
                url,
                {**category_data(doctor, valid_from=PAST, maximum_hours="12"), "reason": "x"},
                follow=True,
            ),
        ):
            assert "em vigor" in response.content.decode()
    rule.refresh_from_db()
    assert rule.maximum_hours == Decimal("14")
    assert not AuditEntry.objects.exists()


def test_deleting_a_future_rule_needs_a_reason_and_is_audited(manager_client):
    """Deletion asks for a reason and is logged."""
    rule = make_rule()
    url = reverse("staff:loadrange_delete", kwargs={"pk": rule.pk})
    manager_client.post(url, {"reason": ""})
    assert LoadRange.objects.exists()
    manager_client.post(url, {"reason": "Criada por engano"})
    assert not LoadRange.objects.exists()
    assert AuditEntry.objects.get().action == "delete"


def test_the_position_choices_exclude_inactive_positions(manager_client):
    """An inactive position is not offered for a new rule."""
    Position.objects.create(name="Ativo")
    Position.objects.create(name="Inativo", is_active=False)
    response = manager_client.get(reverse("staff:loadrange_create"))
    names = {p.name for p in response.context["form"].fields["position"].queryset}
    assert names == {"Ativo"}


def test_menu_shows_the_hours_ranges_link(manager_client):
    """The screen appears in the manager's menu."""
    assert reverse("staff:loadrange_list") in manager_client.get("/").content.decode()
