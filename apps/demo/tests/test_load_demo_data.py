"""Tests for the command that loads the fictitious data set.

Implements: docs/dados_ficticios.md (the part phase 1 already supports); CLAUDE.md rule 8 (no real
data in the repository); D65. The data must be small, clearly fictitious, valid, audited, safe to
load twice and impossible to load in production by accident.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.academic.cross_course import check_group
from apps.academic.models import (
    ClassGroup,
    Coordination,
    Course,
    CrossCourseSubject,
    Faculty,
    StudyPlan,
    Subject,
)
from apps.academic.services import check_semester_load, facts_for
from apps.core.models import AuditEntry, Profile, RoleAssignment, ScopeKind
from apps.core.scopes import faculty_of_scope
from apps.rooms.models import Room
from apps.staff.models import Category, LoadRange, Teacher, TeacherPosition
from apps.staff.services import load_range_for

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def loaded(settings):
    """Load the demo data with DEBUG on (as in development) and return the command output."""
    settings.DEBUG = True
    out = StringIO()
    call_command("load_demo_data", stdout=out)
    return out.getvalue()


# --- safety -------------------------------------------------------------------------------------


def test_it_refuses_to_run_when_debug_is_off(settings):
    """Production safety: nothing is created without DEBUG or --force."""
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("load_demo_data")
    assert not Faculty.objects.exists() and not User.objects.filter(username="demo_gestor").exists()


def test_force_runs_without_debug_but_gives_the_accounts_no_password(settings):
    """With --force outside development the accounts are created unusable (D41)."""
    settings.DEBUG = False
    settings.ALLOW_LOCAL_LOGIN = False
    call_command("load_demo_data", force=True, stdout=StringIO())
    assert Faculty.objects.count() == 2
    for user in User.objects.filter(username__startswith="demo_"):
        assert not user.has_usable_password()


def test_the_demo_accounts_log_in_with_the_demo_password_in_development(loaded):
    """In development each demo account has the documented password."""
    for username in ("demo_gestor", "demo_coordenador", "demo_ce", "demo_patrimonio"):
        assert authenticate(username=username, password="demo1234") is not None


def test_it_never_deletes_existing_data(settings):
    """Whatever is already there stays."""
    settings.DEBUG = True
    Faculty.objects.create(name="Faculdade Existente", code="EXI")
    call_command("load_demo_data", stdout=StringIO())
    assert Faculty.objects.filter(code="EXI").exists()
    assert Faculty.objects.count() == 3


def test_it_can_run_twice_without_duplicating_anything(settings):
    """Idempotent: a second run changes no count and writes no audit entry."""
    settings.DEBUG = True
    call_command("load_demo_data", stdout=StringIO())
    models = [Faculty, Coordination, Course, StudyPlan, Subject, ClassGroup, Teacher, Room, User]
    before = {model: model.objects.count() for model in models}
    entries = AuditEntry.objects.count()
    call_command("load_demo_data", stdout=StringIO())
    assert {model: model.objects.count() for model in models} == before
    assert AuditEntry.objects.count() == entries


# --- the structure that docs/dados_ficticios.md asks for -----------------------------------------


def test_two_faculties_and_four_coordinations_one_with_subjects_in_several_courses(loaded):
    """2 Faculties; 3 to 4 coordinations, one with subjects in several courses."""
    assert Faculty.objects.count() == 2
    assert 3 <= Coordination.objects.count() <= 4
    shared = [
        c
        for c in Coordination.objects.all()
        if len({s.study_plan.course_id for s in c.subjects.all()}) > 1
    ]
    assert shared


def test_three_bachelor_courses_and_one_master_with_two_year_plans(loaded):
    """Each course has a plan with years 1 and 2 and both semesters."""
    assert Course.objects.filter(level=Course.Level.BACHELOR).count() == 3
    assert Course.objects.filter(level=Course.Level.MASTER).count() == 1
    for course in Course.objects.all():
        plan = StudyPlan.objects.get(course=course)
        cells = {(s.curricular_year, s.semester) for s in plan.subjects.all()}
        assert cells == {(1, 1), (1, 2), (2, 1), (2, 2)}


def test_every_course_is_directed_by_a_coordination_of_its_faculty(loaded):
    """The demo links each course to a coordination of the same Faculty (D67)."""
    for course in Course.objects.all():
        assert course.responsible_coordination.faculty_id == course.faculty_id


def test_one_course_has_two_turmas_in_the_same_year_and_the_rest_one(loaded):
    """The future case is covered: 1.º A and 1.º B in one course."""
    per_course = {}
    for group in ClassGroup.objects.all():
        per_course.setdefault((group.course_id, group.intake_year_id), []).append(group.label)
    sizes = sorted(len(labels) for labels in per_course.values())
    assert sizes.count(2) == 1 and set(sizes) <= {1, 2}
    two = next(labels for labels in per_course.values() if len(labels) == 2)
    assert sorted(two) == ["A", "B"]


def test_a_cross_course_subject_is_declared_in_two_courses_and_refused_in_a_third(loaded):
    """Three member courses, two allowed: the group is valid and the third is refused."""
    group = CrossCourseSubject.objects.get()
    members = [facts_for(m.subject) for m in group.members.all()]
    allowed = set(group.allowed_courses.values_list("course_id", flat=True))
    member_courses = {m.course_id for m in members}
    assert len(member_courses) == 3 and len(allowed) == 2 and allowed < member_courses
    assert check_group(members, allowed) == []


def test_teachers_of_every_category_and_type_some_with_positions(loaded):
    """All categories, all types, positions for some, and a range for each of them."""
    teachers = list(Teacher.objects.select_related("category"))
    assert {t.category.name for t in teachers} == {c.name for c in Category.objects.all()}
    assert {t.teacher_type for t in teachers} == {t.value for t in Teacher.Type}
    assert TeacherPosition.objects.exists()
    assert all(
        t.teacher_type == Teacher.Type.FULL_TIME
        for t in Teacher.objects.filter(position_assignments__isnull=False)
    )
    for teacher in teachers:
        assert load_range_for(teacher, date.today()) is not None, teacher


def test_the_hours_ranges_are_in_force_and_are_test_values(loaded):
    """Rules start in the past; the values are for testing, not real University values."""
    assert LoadRange.objects.exists()
    assert all(rule.valid_from <= date.today() for rule in LoadRange.objects.all())


def test_rooms_of_several_types_and_capacities_one_too_small_for_an_exam(loaded):
    """At least three types, a tiny room and an auditorium."""
    rooms = Room.objects.all()
    assert len({room.room_type_id for room in rooms}) >= 3
    capacities = [room.capacity for room in rooms]
    assert min(capacities) <= 15 and max(capacities) >= 100


def test_every_subject_has_weekly_hours_matching_its_semester_hours(loaded):
    """The demo data obeys the 15-week rule of D60."""
    for subject in Subject.objects.all():
        assert subject.class_loads.exists()
        check_semester_load(subject, {})


def test_every_record_passes_its_full_validation(loaded):
    """Nothing invalid is loaded: full_clean on every record of the four apps."""
    for app in ("academic", "staff", "rooms"):
        for model in django_apps.get_app_config(app).get_models():
            for instance in model.objects.all():
                instance.full_clean()


def test_names_are_clearly_fictitious(loaded):
    """No real-looking names: everything carries the test markers."""
    assert all("Teste" in f.name for f in Faculty.objects.all())
    assert all(c.name.startswith("Curso") for c in Course.objects.all())
    assert all(t.name.startswith("Docente") for t in Teacher.objects.all())
    assert all("Teste" in c.name for c in Coordination.objects.all())


def test_all_the_demo_data_went_through_the_audit_log(loaded):
    """Rooms, teachers and subjects have create entries written by the system."""
    for entity in ("rooms.room", "staff.teacher", "academic.subject", "academic.faculty"):
        assert AuditEntry.objects.filter(entity=entity, action="create", actor=None).exists()


# --- the accounts ---


def test_there_is_one_demo_account_per_profile_with_valid_scopes(loaded):
    """A manager, a coordinator, the executive board, Património, Consulta and a teacher."""
    profiles = set(
        RoleAssignment.objects.filter(user__username__startswith="demo_").values_list(
            "profile", flat=True
        )
    )
    assert profiles == {
        Profile.PGC_MANAGER,
        Profile.COORDINATOR,
        Profile.EXECUTIVE_BOARD,
        Profile.FACILITIES,
        Profile.VIEWER,
        Profile.TEACHER,
    }
    for role in RoleAssignment.objects.filter(user__username__startswith="demo_"):
        if role.scope_kind != ScopeKind.NONE:
            assert faculty_of_scope(role.scope_kind, role.scope_id)


def test_the_demo_manager_manages_both_faculties(loaded):
    """So the manager screens can be tried over all the data."""
    manager = User.objects.get(username="demo_gestor")
    faculties = set(
        manager.role_assignments.filter(profile=Profile.PGC_MANAGER).values_list(
            "scope_id", flat=True
        )
    )
    assert faculties == set(Faculty.objects.values_list("pk", flat=True))


def test_the_command_prints_how_to_log_in(loaded):
    """The output tells the developer the accounts and the password."""
    assert "demo_gestor" in loaded and "demo1234" in loaded


def test_the_semester_weeks_parameter_is_not_changed(loaded):
    """The command uses the 15-week parameter, it does not edit it."""
    from apps.core.parameters import SEMESTER_WEEKS, get_parameter

    assert get_parameter(SEMESTER_WEEKS) == Decimal("15")
