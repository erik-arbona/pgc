"""Tests for the preparation hours rule.

Implements: docs/especificacao/05_dsd_regras.md – preparation = theoretical weekly hours +
(theoretical-practical, practical and laboratory weekly hours) x 1.5, kept as a parameter so it
can change without touching the code; D14, D61. The parameter is a weight per class type.
"""

import itertools
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.academic.models import (
    AcademicYear,
    ClassType,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
    SubjectClassLoad,
)
from apps.academic.preparation import preparation_hours
from apps.academic.services import preparation_for
from apps.core.models import AuditEntry

D = Decimal

# The weights of the specification's formula: T counts once, TP, P and L count 1.5 times.
SPEC_WEIGHTS = {"T": D("1"), "TP": D("1.5"), "P": D("1.5"), "L": D("1.5"), "OUT": D("0")}


# --- the pure rule (no database) -----------------------------------------------------------


def test_the_formula_of_the_specification():
    """T 2, TP 1, P 2, L 1: 2 + (1 + 2 + 1) x 1.5 = 8."""
    hours = {"T": D("2"), "TP": D("1"), "P": D("2"), "L": D("1")}
    assert preparation_hours(hours, SPEC_WEIGHTS) == D("8")


def test_three_theory_and_two_practice_hours_need_six_hours_of_preparation():
    """The manager's example subject: 3 T + 2 P = 3 + 2 x 1.5 = 6."""
    assert preparation_hours({"T": D("3"), "P": D("2")}, SPEC_WEIGHTS) == D("6")


def test_a_class_type_with_weight_zero_does_not_count():
    """'Outra' is not in the formula of the specification."""
    assert preparation_hours({"T": D("3"), "OUT": D("4")}, SPEC_WEIGHTS) == D("3")


def test_the_weights_are_data_not_constants():
    """Changing the weight of practical classes to 2 changes the result."""
    weights = {**SPEC_WEIGHTS, "P": D("2")}
    assert preparation_hours({"T": D("3"), "P": D("2")}, weights) == D("7")


def test_a_new_class_type_counts_once_its_weight_is_set():
    """A type that the code does not know counts as soon as it has a weight."""
    weights = {**SPEC_WEIGHTS, "SEM": D("1.25")}
    assert preparation_hours({"SEM": D("2")}, weights) == D("2.5")


def test_no_hours_give_zero():
    """An empty subject has no preparation."""
    assert preparation_hours({}, SPEC_WEIGHTS) == D("0")
    assert preparation_hours({"T": D("0")}, SPEC_WEIGHTS) == D("0")


def test_half_hours_and_decimal_weights_are_exact():
    """2.5 theory + 2.5 practical = 2.5 + 3.75 = 6.25, with no rounding error."""
    assert preparation_hours({"T": D("2.5"), "P": D("2.5")}, SPEC_WEIGHTS) == D("6.25")


def test_hours_of_a_class_type_without_weight_are_an_error():
    """A class type missing from the weights is a programming error, never a silent zero."""
    with pytest.raises(ValueError):
        preparation_hours({"XYZ": D("1")}, SPEC_WEIGHTS)


def test_negative_hours_or_weights_are_an_error():
    """Inconsistent input is refused."""
    with pytest.raises(ValueError):
        preparation_hours({"T": D("-1")}, SPEC_WEIGHTS)
    with pytest.raises(ValueError):
        preparation_hours({"T": D("1")}, {"T": D("-1")})


def test_the_order_of_the_hours_does_not_matter():
    """The same hours in another order give the same result."""
    a = {"T": D("1"), "TP": D("2"), "P": D("3"), "L": D("4")}
    b = dict(reversed(list(a.items())))
    assert preparation_hours(a, SPEC_WEIGHTS) == preparation_hours(b, SPEC_WEIGHTS)


def test_exhaustive_agreement_with_the_formula_written_out():
    """For every combination of hours, the result is T + (TP + P + L) x 1.5."""
    values = (D("0"), D("1"), D("2.5"))
    checked = 0
    for t, tp, p, lab, other in itertools.product(values, repeat=5):
        hours = {"T": t, "TP": tp, "P": p, "L": lab, "OUT": other}
        assert preparation_hours(hours, SPEC_WEIGHTS) == t + (tp + p + lab) * D("1.5")
        checked += 1
    assert checked == 3**5


# --- the weights stored on the class types -------------------------------------------------


@pytest.mark.django_db
def test_the_migration_loads_the_weights_of_the_specification():
    """T = 1, TP = P = L = 1.5 and 'Outra' = 0 after migrating."""
    weights = {ct.code: ct.preparation_weight for ct in ClassType.objects.all()}
    assert weights == SPEC_WEIGHTS


@pytest.mark.django_db
def test_a_new_class_type_starts_with_weight_zero():
    """A type created by the manager does not count in the preparation until they decide."""
    assert ClassType.objects.create(code="SEM", name="Seminário").preparation_weight == 0


@pytest.mark.django_db
def test_the_weight_cannot_be_negative():
    """The database refuses a negative weight."""
    with pytest.raises(IntegrityError), transaction.atomic():
        ClassType.objects.create(code="NEG", name="Negativo", preparation_weight=D("-1"))


@pytest.fixture
def subject(db):
    """A subject with 3 theory and 2 practice weekly hours."""
    faculty = Faculty.objects.create(name="FCT", code="FCT")
    plan = StudyPlan.objects.create(
        course=Course.objects.create(faculty=faculty, name="Eng", level="bachelor"),
        academic_year=AcademicYear.objects.create(start_year=2026),
    )
    item = Subject.objects.create(
        study_plan=plan,
        code="P1",
        name="Prog",
        ects=D("6"),
        curricular_year=1,
        semester=1,
        coordination=Coordination.objects.create(faculty=faculty, name="Inf"),
        semester_hours=D("75"),
    )
    for code, hours in (("T", 3), ("P", 2)):
        SubjectClassLoad.objects.create(
            subject=item, class_type=ClassType.objects.get(code=code), weekly_hours=hours
        )
    return item


@pytest.mark.django_db
def test_the_service_computes_the_preparation_of_a_subject(subject):
    """3 T + 2 P = 6 hours of weekly preparation."""
    assert preparation_for(subject) == D("6")


@pytest.mark.django_db
def test_the_service_uses_the_current_weights(subject):
    """If the manager changes the weight of P to 2, the result follows."""
    ClassType.objects.filter(code="P").update(preparation_weight=D("2"))
    assert preparation_for(subject) == D("7")


@pytest.mark.django_db
def test_the_class_type_form_edits_the_weight_with_a_reason(manager_client):
    """The manager sets the weight on the class type screen; it is audited."""
    seminar = ClassType.objects.create(code="SEM", name="Seminário")
    url = reverse("academic:classtype_update", kwargs={"pk": seminar.pk})
    data = {
        "code": "SEM",
        "name": "Seminário",
        "position": 100,
        "is_active": "on",
        "preparation_weight": "1.25",
    }
    manager_client.post(url, data)
    seminar.refresh_from_db()
    assert seminar.preparation_weight == 0
    manager_client.post(url, {**data, "reason_choice": "data_update"})
    seminar.refresh_from_db()
    assert seminar.preparation_weight == D("1.25")
    assert AuditEntry.objects.filter(entity="academic.classtype", action="update").exists()


@pytest.mark.django_db
def test_a_negative_weight_is_a_form_error(manager_client):
    """The form refuses it with a message on the field."""
    seminar = ClassType.objects.create(code="SEM", name="Seminário")
    response = manager_client.post(
        reverse("academic:classtype_update", kwargs={"pk": seminar.pk}),
        {
            "code": "SEM",
            "name": "Seminário",
            "position": 100,
            "is_active": "on",
            "preparation_weight": "-1",
            "reason": "x",
        },
    )
    assert response.status_code == 200
    assert "preparation_weight" in response.context["form"].errors


@pytest.mark.django_db
def test_the_class_type_list_shows_the_weights(manager_client):
    """The weights appear in the class type list."""
    page = manager_client.get(reverse("academic:classtype_list")).content.decode()
    assert "Peso na preparação" in page and "1,50" in page


@pytest.mark.django_db
def test_the_subject_list_shows_the_preparation_hours(client, subject):
    """The subject list has a preparation column with 6 hours for 3 T + 2 P."""
    from django.contrib.auth import get_user_model

    from apps.core.models import Profile, RoleAssignment, ScopeKind

    user = get_user_model().objects.create_user(username="gestor", password="x")
    RoleAssignment.objects.create(
        user=user,
        profile=Profile.PGC_MANAGER,
        scope_kind=ScopeKind.FACULTY,
        scope_id=subject.study_plan.course.faculty_id,
    )
    client.force_login(user)
    page = client.get(reverse("academic:subject_list")).content.decode()
    assert "Preparação" in page and "6,00" in page
