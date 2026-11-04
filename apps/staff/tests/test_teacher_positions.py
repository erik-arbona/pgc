"""Tests for the positions inside the teacher form (T3.1, part 4).

Implements: docs/especificacao/02_perfis_e_dados.md – positions assigned by the PGC manager;
D40 (one audit entry per row, shared reason), D53 (same pattern as subject hours), D56
(only full-time teachers hold positions).
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.core.models import AuditEntry
from apps.staff.models import Position, Teacher, TeacherPosition
from apps.staff.services import save_teacher_with_positions
from apps.staff.tests.test_teacher_views import Setup, manager_of

pytestmark = pytest.mark.django_db


@pytest.fixture
def a():
    """Faculty A."""
    return Setup("A")


@pytest.fixture
def actor():
    """The user writing the data."""
    return get_user_model().objects.create_user(username="gestor", password="x")


@pytest.fixture
def chief():
    """A position."""
    return Position.objects.create(name="Presidente de conselho")


@pytest.fixture
def adviser():
    """Another position."""
    return Position.objects.create(name="Assessor")


def new_teacher(a, identifier="N001", **overrides):
    """Build an unsaved full-time teacher of Faculty A."""
    from apps.staff.models import Category

    data = dict(
        identifier=identifier,
        name="Novo Docente",
        coordination=a.coordination,
        category=Category.objects.get(name="Doutor"),
        teacher_type=Teacher.Type.FULL_TIME,
    )
    data.update(overrides)
    return Teacher(**data)


def held(teacher):
    """Return the names of the positions a teacher holds."""
    return set(teacher.position_assignments.values_list("position__name", flat=True))


def entries(entity):
    """Return the audit actions logged for an entity, in order."""
    return list(
        AuditEntry.objects.filter(entity=entity).order_by("pk").values_list("action", flat=True)
    )


def test_creating_a_teacher_with_positions_audits_every_row(a, actor, chief, adviser):
    """One entry for the teacher and one for each position."""
    teacher = new_teacher(a)
    save_teacher_with_positions(teacher, {chief.pk, adviser.pk}, actor, "", save_teacher=True)
    assert held(teacher) == {"Presidente de conselho", "Assessor"}
    assert entries("staff.teacher") == ["create"]
    assert entries("staff.teacherposition") == ["create", "create"]


def test_updating_positions_adds_and_removes_rows_with_the_same_reason(a, actor, chief, adviser):
    """Removing one and adding another logs a delete and a create; the teacher is untouched."""
    teacher = a.teacher()
    TeacherPosition.objects.create(teacher=teacher, position=chief)
    save_teacher_with_positions(teacher, {adviser.pk}, actor, "Novo mandato", save_teacher=False)
    assert held(teacher) == {"Assessor"}
    assert sorted(entries("staff.teacherposition")) == ["create", "delete"]
    assert entries("staff.teacher") == []
    assert all(
        e.reason == "Novo mandato"
        for e in AuditEntry.objects.filter(entity="staff.teacherposition")
    )


def test_unchanged_positions_write_nothing(a, actor, chief):
    """Saving the same set logs nothing."""
    teacher = a.teacher()
    TeacherPosition.objects.create(teacher=teacher, position=chief)
    save_teacher_with_positions(teacher, {chief.pk}, actor, "Sem alterações", save_teacher=False)
    assert not AuditEntry.objects.exists()


def test_the_type_can_change_in_the_same_save_that_removes_the_positions(a, actor, chief):
    """The rows are removed first, so the teacher can then stop being full-time."""
    teacher = a.teacher()
    TeacherPosition.objects.create(teacher=teacher, position=chief)
    teacher.teacher_type = Teacher.Type.HABITUAL_COLLABORATOR
    save_teacher_with_positions(teacher, set(), actor, "Passou a colaborador", save_teacher=True)
    teacher.refresh_from_db()
    assert teacher.teacher_type == Teacher.Type.HABITUAL_COLLABORATOR
    assert not teacher.position_assignments.exists()
    assert entries("staff.teacherposition") == ["delete"]


def test_an_inactive_position_is_refused_and_nothing_is_saved(a, actor):
    """The whole save is atomic: a refused row means the new teacher is not created either."""
    old = Position.objects.create(name="Antigo", is_active=False)
    with pytest.raises(ValidationError):
        save_teacher_with_positions(new_teacher(a), {old.pk}, actor, "", save_teacher=True)
    assert not Teacher.objects.exists()
    assert not AuditEntry.objects.exists()


def test_the_form_offers_active_positions_and_the_ones_already_held(client, a, chief):
    """An inactive position appears only for the teacher who already holds it."""
    old = Position.objects.create(name="Antigo")
    teacher = a.teacher()
    other = a.teacher("A2", "Outro")
    TeacherPosition.objects.create(teacher=teacher, position=chief)
    TeacherPosition.objects.create(teacher=teacher, position=old)
    old.is_active = False  # deactivated after it was assigned
    old.save()
    manager_of(client, a.faculty)
    own = client.get(reverse("staff:teacher_update", kwargs={"pk": teacher.pk}))
    others = client.get(reverse("staff:teacher_update", kwargs={"pk": other.pk}))
    assert {p.name for p in own.context["form"].fields["positions"].queryset} == {
        "Presidente de conselho",
        "Antigo",
    }
    assert {p.name for p in others.context["form"].fields["positions"].queryset} == {
        "Presidente de conselho"
    }


def test_posting_a_new_teacher_saves_the_positions(client, a, chief, adviser):
    """Positions chosen in the form are saved with the teacher."""
    manager_of(client, a.faculty)
    client.post(
        reverse("staff:teacher_create"),
        {**a.post_data(), "positions": [chief.pk, adviser.pk]},
    )
    assert held(Teacher.objects.get()) == {"Presidente de conselho", "Assessor"}


@pytest.mark.parametrize("kind", ["habitual_collaborator", "competition"])
def test_positions_on_a_collaborator_or_competition_teacher_are_a_form_error(
    client, a, chief, kind
):
    """Only full-time teachers hold positions: the form says so on the positions field."""
    manager_of(client, a.faculty)
    response = client.post(
        reverse("staff:teacher_create"),
        {**a.post_data(teacher_type=kind), "positions": [chief.pk]},
    )
    assert response.status_code == 200
    assert "positions" in response.context["form"].errors
    assert not Teacher.objects.exists()


def test_changing_positions_needs_a_reason(client, a, chief, adviser):
    """Without a reason neither the teacher nor the positions change."""
    teacher = a.teacher()
    TeacherPosition.objects.create(teacher=teacher, position=chief)
    manager_of(client, a.faculty)
    url = reverse("staff:teacher_update", kwargs={"pk": teacher.pk})
    data = {
        **a.post_data(identifier=teacher.identifier, name=teacher.name),
        "positions": [adviser.pk],
    }
    client.post(url, data)
    assert held(teacher) == {"Presidente de conselho"}
    assert not AuditEntry.objects.exists()
    client.post(url, {**data, "reason": "Novo mandato"})
    assert held(teacher) == {"Assessor"}


def test_a_type_change_that_clears_the_positions_works_through_the_form(client, a, chief):
    """Unchecking every position and choosing collaborator is one valid save."""
    teacher = a.teacher()
    TeacherPosition.objects.create(teacher=teacher, position=chief)
    manager_of(client, a.faculty)
    client.post(
        reverse("staff:teacher_update", kwargs={"pk": teacher.pk}),
        a.post_data(
            identifier=teacher.identifier,
            name=teacher.name,
            teacher_type="habitual_collaborator",
            reason="Passou a colaborador",
        ),
    )
    teacher.refresh_from_db()
    assert teacher.teacher_type == Teacher.Type.HABITUAL_COLLABORATOR
    assert not teacher.position_assignments.exists()
