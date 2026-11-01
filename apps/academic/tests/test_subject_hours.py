"""Tests for the weekly hours per class type inside the subject form (T2.6, part 5).

Implements: docs/especificacao/02_perfis_e_dados.md – weekly load split by class type;
D40 (one audit entry per row written, one shared reason), D44, D53.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.academic.models import ClassType, Subject, SubjectClassLoad
from apps.academic.services import save_subject_with_loads
from apps.academic.tests.test_plan_subject_views import Setup, manager_of
from apps.core.models import AuditEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def a():
    """Faculty A and its data."""
    return Setup("A")


@pytest.fixture
def actor():
    """The user writing the data."""
    return get_user_model().objects.create_user(username="gestor", password="x")


def kinds():
    """Return the codes of the class types by code."""
    return {ct.code: ct for ct in ClassType.objects.all()}


def new_subject(a, code="NEW"):
    """Build an unsaved subject of Faculty A's plan."""
    return Subject(
        study_plan=a.plan,
        code=code,
        name="Introdução à Programação",
        ects=Decimal("6"),
        curricular_year=1,
        semester=1,
        coordination=a.coordination,
        semester_hours=Decimal("75"),
    )


def hours_of(subject):
    """Return the weekly hours of a subject keyed by class type code."""
    return {
        load.class_type.code: load.weekly_hours
        for load in subject.class_loads.select_related("class_type")
    }


def entries(entity):
    """Return the audit actions logged for an entity, in order."""
    return list(
        AuditEntry.objects.filter(entity=entity).order_by("pk").values_list("action", flat=True)
    )


def test_creating_a_subject_with_loads_audits_every_row(a, actor):
    """3 h of T and 2 h of P: one subject entry and two load entries."""
    ct = kinds()
    subject = new_subject(a)
    save_subject_with_loads(
        subject, {ct["T"].pk: Decimal("3"), ct["P"].pk: Decimal("2")}, actor, "", save_subject=True
    )
    assert hours_of(subject) == {"T": Decimal("3.00"), "P": Decimal("2.00")}
    assert subject.weekly_hours_total == Decimal("5")
    assert entries("academic.subject") == ["create"]
    assert entries("academic.subjectclassload") == ["create", "create"]


def test_updating_loads_creates_changes_and_removes_rows(a, actor):
    """T 3 to 2, P removed with a blank value, L added; each row logs its own action."""
    ct = kinds()
    subject = a.subject()
    SubjectClassLoad.objects.create(subject=subject, class_type=ct["T"], weekly_hours=3)
    SubjectClassLoad.objects.create(subject=subject, class_type=ct["P"], weekly_hours=2)
    save_subject_with_loads(
        subject,
        {ct["T"].pk: Decimal("2"), ct["P"].pk: None, ct["L"].pk: Decimal("1")},
        actor,
        "Revisão do plano",
        save_subject=False,
    )
    assert hours_of(subject) == {"T": Decimal("2.00"), "L": Decimal("1.00")}
    actions = set(entries("academic.subjectclassload"))
    assert actions == {"update", "delete", "create"}
    assert all(
        e.reason == "Revisão do plano"
        for e in AuditEntry.objects.filter(entity="academic.subjectclassload")
    )
    assert entries("academic.subject") == []  # the subject itself did not change


def test_zero_hours_removes_the_row(a, actor):
    """Zero means no hours of that class type."""
    ct = kinds()
    subject = a.subject()
    SubjectClassLoad.objects.create(subject=subject, class_type=ct["T"], weekly_hours=3)
    save_subject_with_loads(
        subject, {ct["T"].pk: Decimal("0")}, actor, "Sem teóricas", save_subject=False
    )
    assert hours_of(subject) == {}


def test_unchanged_hours_write_nothing(a, actor):
    """Saving the same values logs no load entry."""
    ct = kinds()
    subject = a.subject()
    SubjectClassLoad.objects.create(subject=subject, class_type=ct["T"], weekly_hours=3)
    save_subject_with_loads(
        subject, {ct["T"].pk: Decimal("3")}, actor, "Sem alterações", save_subject=False
    )
    assert not AuditEntry.objects.exists()


def test_an_inactive_class_type_cannot_get_new_hours_and_nothing_is_saved(a, actor):
    """The whole save is atomic: the subject is not created if a row is refused."""
    ct = kinds()
    ct["OUT"].is_active = False
    ct["OUT"].save()
    with pytest.raises(ValidationError):
        save_subject_with_loads(
            new_subject(a), {ct["OUT"].pk: Decimal("1")}, actor, "", save_subject=True
        )
    assert not Subject.objects.exists()
    assert not AuditEntry.objects.exists()


def test_the_form_offers_one_hours_field_per_active_class_type(client, a):
    """T, TP, P, L and OUT are offered; an inactive type without hours is not."""
    ct = kinds()
    ct["OUT"].is_active = False
    ct["OUT"].save()
    manager_of(client, a.faculty)
    response = client.get(reverse("academic:subject_create"))
    fields = set(response.context["form"].fields)
    assert {f"hours_{ct[c].pk}" for c in ("T", "TP", "P", "L")} <= fields
    assert f"hours_{ct['OUT'].pk}" not in fields


def test_the_form_keeps_an_inactive_type_that_still_has_hours(client, a):
    """An existing load of a deactivated type stays visible and editable."""
    ct = kinds()
    subject = a.subject()
    SubjectClassLoad.objects.create(subject=subject, class_type=ct["OUT"], weekly_hours=1)
    ct["OUT"].is_active = False
    ct["OUT"].save()
    manager_of(client, a.faculty)
    response = client.get(reverse("academic:subject_update", kwargs={"pk": subject.pk}))
    assert f"hours_{ct['OUT'].pk}" in response.context["form"].fields


def test_posting_a_new_subject_saves_its_weekly_hours(client, a):
    """The manager's example: 3 theory and 2 practice make 5 weekly hours."""
    ct = kinds()
    manager_of(client, a.faculty)
    data = {**a.post_data("subject", code="IP1", name="Intro"), "semester_hours": "75"}
    data[f"hours_{ct['T'].pk}"] = "3"
    data[f"hours_{ct['P'].pk}"] = "2"
    client.post(reverse("academic:subject_create"), data)
    subject = Subject.objects.get(code="IP1")
    assert subject.weekly_hours_total == Decimal("5")
    page = client.get(reverse("academic:subject_list")).content.decode()
    assert "5,00" in page or "5.00" in page


def test_updating_hours_needs_a_reason_and_changes_nothing_without_it(client, a):
    """Without a reason neither the subject nor the hours change."""
    ct = kinds()
    subject = a.subject()
    SubjectClassLoad.objects.create(subject=subject, class_type=ct["T"], weekly_hours=3)
    manager_of(client, a.faculty)
    url = reverse("academic:subject_update", kwargs={"pk": subject.pk})
    data = {**a.post_data("subject", code=subject.code, name=subject.name), "reason": ""}
    data[f"hours_{ct['T'].pk}"] = "1"
    client.post(url, data)
    assert hours_of(subject) == {"T": Decimal("3.00")}
    client.post(url, {**data, "reason": "Corrigir carga"})
    assert hours_of(subject) == {"T": Decimal("1.00")}
    assert "update" in entries("academic.subjectclassload")


def test_negative_hours_are_a_form_error(client, a):
    """The form refuses negative hours before touching the database."""
    ct = kinds()
    manager_of(client, a.faculty)
    data = a.post_data("subject", code="NEG")
    data[f"hours_{ct['T'].pk}"] = "-1"
    response = client.post(reverse("academic:subject_create"), data)
    assert response.status_code == 200
    assert not Subject.objects.exists()
