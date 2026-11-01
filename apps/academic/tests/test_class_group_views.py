"""View tests for the turma (class group) screens, scoped to the manager's Faculties.

Implements: docs/especificacao/04_modelo_de_dados.md – turmas; 07_arquitetura.md – optimistic
locking on turmas and audit of every change; D48, D49, D51, D54.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.academic.models import AcademicYear, ClassGroup, StudyPlan
from apps.academic.services import create_class_group
from apps.academic.tests.test_plan_subject_views import Setup, manager_of
from apps.core.audit import audited_save
from apps.core.models import AuditEntry, Profile

pytestmark = pytest.mark.django_db


@pytest.fixture
def a():
    """Faculty A and its data (course with a plan that starts in 2026)."""
    return Setup("A")


@pytest.fixture
def b():
    """Faculty B and its data."""
    return Setup("B")


@pytest.fixture
def actor():
    """A user used to create fixtures through the audited service."""
    return get_user_model().objects.create_user(username="fixture", password="x")


def year(start):
    """Get or create an academic year."""
    return AcademicYear.objects.get_or_create(start_year=start)[0]


def make_group(setup, actor, intake=2026, label="", last=None):
    """Create a turma through the audited service."""
    return create_class_group(
        setup.course,
        year(intake),
        label,
        year(last) if last else None,
        actor=actor,
    )


def create_data(setup, intake=2026, label="", last=""):
    """Valid POST data to create a turma."""
    return {
        "course": setup.course.pk,
        "intake_year": year(intake).pk,
        "label": label,
        "last_academic_year": year(last).pk if last else "",
    }


def update_data(group, **overrides):
    """Valid POST data to edit a turma, carrying the version the form showed."""
    data = {
        "label": group.label,
        "last_academic_year": group.last_academic_year_id or "",
        "version": group.version,
        "reason": "Correção",
    }
    data.update(overrides)
    return data


def test_anonymous_visitors_are_redirected_to_login(client):
    """The list requires a session."""
    response = client.get(reverse("academic:classgroup_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize("profile", [p for p in Profile if p != Profile.PGC_MANAGER])
def test_other_profiles_get_403(client, make_user, a, profile):
    """Only the PGC manager reaches the turma screens."""
    client.force_login(make_user(profile))
    for name in ("list", "create"):
        url = reverse(f"academic:classgroup_{name}")
        assert client.get(url).status_code == 403
        assert client.post(url, create_data(a)).status_code == 403
    assert not ClassGroup.objects.exists()


def test_a_superuser_without_assignment_gets_403(client):
    """The superuser flag gives no business access (D39)."""
    client.force_login(get_user_model().objects.create_superuser(username="root", password="x"))
    assert client.get(reverse("academic:classgroup_list")).status_code == 403


def test_the_list_shows_only_the_managers_faculties(client, a, b, actor):
    """A manager of A sees A's turmas and not B's."""
    make_group(a, actor)
    make_group(b, actor)
    manager_of(client, a.faculty)
    page = client.get(reverse("academic:classgroup_list")).content.decode()
    assert "Curso A" in page and "Curso B" not in page


def test_a_manager_cannot_touch_another_faculty_turma(client, a, b, actor):
    """Editing or deleting a turma of B as a manager of A gives 403 and changes nothing."""
    group = make_group(b, actor)
    manager_of(client, a.faculty)
    before = AuditEntry.objects.count()
    for action in ("update", "delete"):
        url = reverse(f"academic:classgroup_{action}", kwargs={"pk": group.pk})
        assert client.get(url).status_code == 403
        assert client.post(url, {**update_data(group), "reason": "x"}).status_code == 403
    assert AuditEntry.objects.count() == before


def test_creating_in_another_faculty_is_refused(client, a, b):
    """The form only offers the manager's courses."""
    manager_of(client, a.faculty)
    response = client.post(reverse("academic:classgroup_create"), create_data(b))
    assert response.status_code == 200
    assert "course" in response.context["form"].errors
    assert not ClassGroup.objects.exists()


def test_creating_a_turma_resolves_the_plan_and_is_audited(client, a):
    """The plan in force for the first year is chosen by the system, and the creation is audited."""
    newer = StudyPlan.objects.create(course=a.course, academic_year=year(2027))
    manager_of(client, a.faculty)
    client.post(reverse("academic:classgroup_create"), create_data(a, intake=2027))
    group = ClassGroup.objects.get()
    assert group.study_plan == newer
    entry = AuditEntry.objects.get(entity="academic.classgroup")
    assert (entry.action, entry.entity_id, entry.actor.username) == (
        "create",
        str(group.pk),
        "gestor",
    )


def test_creating_a_turma_with_no_plan_in_force_is_a_form_error(client, a):
    """Intake before the first plan: a message on the form and nothing saved."""
    manager_of(client, a.faculty)
    response = client.post(reverse("academic:classgroup_create"), create_data(a, intake=2020))
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    assert not ClassGroup.objects.exists()


def test_the_same_label_twice_is_a_form_error(client, a, actor):
    """1.º A twice for the same intake is refused."""
    make_group(a, actor, label="A")
    manager_of(client, a.faculty)
    response = client.post(reverse("academic:classgroup_create"), create_data(a, label="A"))
    assert response.status_code == 200
    assert ClassGroup.objects.count() == 1


def test_a_last_year_before_the_intake_is_a_form_error(client, a):
    """A turma cannot end before it starts."""
    manager_of(client, a.faculty)
    response = client.post(
        reverse("academic:classgroup_create"), create_data(a, intake=2026, last=2025)
    )
    assert response.status_code == 200
    assert not ClassGroup.objects.exists()


def test_editing_needs_a_reason_and_is_audited(client, a, actor):
    """No reason: refused. With a reason: the last year is set and logged."""
    group = make_group(a, actor)
    manager_of(client, a.faculty)
    url = reverse("academic:classgroup_update", kwargs={"pk": group.pk})
    data = update_data(group, last_academic_year=year(2028).pk)
    client.post(url, {**data, "reason": ""})
    group.refresh_from_db()
    assert group.last_academic_year is None
    client.post(url, data)
    group.refresh_from_db()
    assert group.last_academic_year.start_year == 2028
    entry = AuditEntry.objects.filter(entity="academic.classgroup", action="update").get()
    assert entry.reason == "Correção"


def test_course_intake_year_and_plan_cannot_be_changed_by_editing(client, a, b, actor):
    """The edit form only touches the label and the last year."""
    group = make_group(a, actor)
    manager_of(client, a.faculty, b.faculty)
    url = reverse("academic:classgroup_update", kwargs={"pk": group.pk})
    client.post(
        url,
        update_data(group, label="B", course=b.course.pk, intake_year=year(2030).pk),
    )
    group.refresh_from_db()
    assert (group.label, group.course, group.intake_year.start_year) == ("B", a.course, 2026)


def test_a_stale_version_is_refused_and_a_fresh_one_is_accepted(client, a, actor):
    """Optimistic locking: a second editor with an old form cannot overwrite the first."""
    group = make_group(a, actor)
    manager_of(client, a.faculty)
    url = reverse("academic:classgroup_update", kwargs={"pk": group.pk})
    shown = client.get(url).context["form"].initial["version"]
    assert shown == group.version
    # Someone else saves first.
    other = ClassGroup.objects.get(pk=group.pk)
    other.label = "X"
    audited_save(other, actor, "Outro utilizador")
    stale = client.post(url, update_data(group, label="Y", version=shown))
    assert stale.status_code == 200
    assert stale.context["form"].non_field_errors()
    assert ClassGroup.objects.get(pk=group.pk).label == "X"
    fresh = ClassGroup.objects.get(pk=group.pk)
    client.post(url, update_data(fresh, label="Y"))
    assert ClassGroup.objects.get(pk=group.pk).label == "Y"


def test_saving_a_turma_increments_its_version(a, actor):
    """Each save moves the version forward by one."""
    group = make_group(a, actor)
    start = group.version
    group.label = "A"
    audited_save(group, actor, "Etiqueta")
    assert ClassGroup.objects.get(pk=group.pk).version == start + 1


def test_a_model_save_with_a_stale_version_raises(a, actor):
    """The conflict is detected in the model, not only in the form."""
    group = make_group(a, actor)
    stale = ClassGroup.objects.get(pk=group.pk)
    fresh = ClassGroup.objects.get(pk=group.pk)
    fresh.label = "A"
    audited_save(fresh, actor, "Primeiro")
    stale.label = "B"
    with pytest.raises(ValidationError):
        audited_save(stale, actor, "Segundo")


def test_deleting_a_turma_is_audited(client, a, actor):
    """Deletion asks for a reason and is logged."""
    group = make_group(a, actor)
    manager_of(client, a.faculty)
    url = reverse("academic:classgroup_delete", kwargs={"pk": group.pk})
    client.post(url, {"reason": ""})
    assert ClassGroup.objects.exists()
    client.post(url, {"reason": "Engano"})
    assert not ClassGroup.objects.exists()
    assert AuditEntry.objects.filter(entity="academic.classgroup", action="delete").exists()


def test_creating_a_turma_by_the_service_is_audited(a, actor):
    """The service writes through audited_save, so the creation is in the audit log."""
    group = make_group(a, actor)
    assert AuditEntry.objects.filter(
        entity="academic.classgroup", entity_id=str(group.pk), action="create"
    ).exists()


def test_menu_shows_the_turmas_link(client, a):
    """The turmas screen appears in the manager's menu."""
    manager_of(client, a.faculty)
    assert reverse("academic:classgroup_list") in client.get("/").content.decode()
