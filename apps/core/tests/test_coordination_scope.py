"""Tests for the reusable coordination-scope checks of ``core.permissions``.

Implements: docs/especificacao/07_arquitetura.md – permissions with scope, always checked on
the server; D09 (the teacher only reads their own distribution), D38, D39 (no pass for
superusers, exact scope in ``can``), D51, D62, D69 (who covers a coordination).

The expected values come from ``expected_cover``, a small oracle written out by hand from
the D69 rule, never derived from the code under test. Entities get explicit ids so that the
same number appears as a Faculty, a coordination and a teacher: a check that confused scope
kinds would then give the wrong answer.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured

from apps.academic.models import Coordination, Faculty
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.core.permissions import PermissionRegistry
from apps.staff.models import Category, Teacher

pytestmark = pytest.mark.django_db

# Explicit ids with deliberate collisions between kinds (see module docstring).
F1, F2 = 10, 20  # Faculties
C1, C2, C3 = 20, 30, 10  # coordinations: C1 and C2 in F1, C3 in F2
T1, T2 = 20, 30  # teachers: T1 in C1, T2 in C3
FACULTY_OF = {C1: F1, C2: F1, C3: F2}

# (scope kind, scope id) assignments to try, including kinds the profile does not admit.
ASSIGNMENTS = [
    (ScopeKind.COORDINATION, C1),
    (ScopeKind.COORDINATION, C3),
    (ScopeKind.FACULTY, F1),
    (ScopeKind.FACULTY, F2),
    (ScopeKind.TEACHER, T1),
    (ScopeKind.NONE, None),
]
READ_PROFILES = {
    Profile.COORDINATOR,
    Profile.EXECUTIVE_BOARD,
    Profile.PGC_MANAGER,
    Profile.TEACHER,
    Profile.VIEWER,
}
WRITE_PROFILES = {Profile.COORDINATOR, Profile.PGC_MANAGER}


@pytest.fixture
def reg() -> PermissionRegistry:
    """An isolated registry with one action of each shape, so the global one is untouched."""
    registry = PermissionRegistry()
    registry.register("x.write", WRITE_PROFILES, write=True, scoped=True)
    registry.register("x.read", READ_PROFILES, write=False, scoped=True)
    # The coordinator reads every distribution of every Faculty: an unscoped read (D69).
    registry.register("x.read_all", {Profile.COORDINATOR}, write=False)
    registry.register("x.unscoped_write", {Profile.PGC_MANAGER}, write=True)
    return registry


@pytest.fixture
def world():
    """F1 with C1 and C2, F2 with C3, and two teachers, all with explicit ids."""
    Faculty.objects.create(pk=F1, name="F1", code="F1")
    Faculty.objects.create(pk=F2, name="F2", code="F2")
    for pk, faculty in ((C1, F1), (C2, F1), (C3, F2)):
        Coordination.objects.create(pk=pk, faculty_id=faculty, name=f"C{pk}")
    doctor = Category.objects.get(name="Doutor")
    for pk, coordination in ((T1, C1), (T2, C3)):
        Teacher.objects.create(
            pk=pk,
            identifier=f"T{pk}",
            name=f"Docente {pk}",
            coordination_id=coordination,
            category=doctor,
            teacher_type=Teacher.Type.FULL_TIME,
        )


def user_with(profile, kind, scope_id, username="u"):
    """A user holding one assignment, created without ``clean`` so wrong kinds are possible."""
    user = get_user_model().objects.create_user(username=username, password="x")
    RoleAssignment.objects.create(user=user, profile=profile, scope_kind=kind, scope_id=scope_id)
    return user


def expected_cover(profile, kind, scope_id, target) -> bool:
    """D69 by hand: does this assignment cover the coordination ``target``?"""
    if profile == Profile.COORDINATOR:
        return kind == ScopeKind.COORDINATION and scope_id == target
    if profile in (Profile.EXECUTIVE_BOARD, Profile.PGC_MANAGER):
        return kind == ScopeKind.FACULTY and scope_id == FACULTY_OF[target]
    return False  # teacher, viewer, academic services and facilities never cover one


@pytest.mark.parametrize("target", [C1, C2, C3])
@pytest.mark.parametrize(("kind", "scope_id"), ASSIGNMENTS)
@pytest.mark.parametrize("profile", list(Profile))
@pytest.mark.parametrize("code", ["x.write", "x.read"])
def test_coordination_check_matches_the_rule_for_every_profile_scope_and_target(
    world, reg, code, profile, kind, scope_id, target
):
    """Full matrix: the coordinator needs their own coordination, the CE and the manager the
    Faculty of the coordination, everybody else never; the action must also admit the profile."""
    user = user_with(profile, kind, scope_id)
    action_profiles = WRITE_PROFILES if code == "x.write" else READ_PROFILES
    expected = profile in action_profiles and expected_cover(profile, kind, scope_id, target)
    assert reg.can_on_coordination(user, code, target) is expected


@pytest.mark.parametrize(("kind", "scope_id"), ASSIGNMENTS)
@pytest.mark.parametrize("profile", list(Profile))
def test_coordination_ids_list_exactly_the_covered_coordinations(
    world, reg, profile, kind, scope_id
):
    """The list used to filter screens agrees with the single check, coordination by one."""
    user = user_with(profile, kind, scope_id)
    for code in ("x.write", "x.read"):
        expected = {c for c in (C1, C2, C3) if reg.can_on_coordination(user, code, c)}
        assert reg.coordination_ids(user, code) == expected


def test_a_manager_reaches_every_coordination_of_their_faculties_only(world, reg):
    """A manager of F1 reaches C1 and C2 but not C3; with F2 as well, all three (D51)."""
    user = user_with(Profile.PGC_MANAGER, ScopeKind.FACULTY, F1)
    assert reg.coordination_ids(user, "x.write") == {C1, C2}
    RoleAssignment.objects.create(
        user=user, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.FACULTY, scope_id=F2
    )
    assert reg.coordination_ids(user, "x.write") == {C1, C2, C3}


def test_a_coordinator_reaches_only_their_own_coordination_for_writing(world, reg):
    """A coordinator of C1 may not write in C2, a sibling in the same Faculty (D69)."""
    user = user_with(Profile.COORDINATOR, ScopeKind.COORDINATION, C1)
    assert reg.can_on_coordination(user, "x.write", C1)
    assert not reg.can_on_coordination(user, "x.write", C2)


def test_a_coordinator_reads_every_distribution_but_writes_only_their_own(world, reg):
    """The coordinator reads all distributions of all Faculties (unscoped read) yet may only
    distribute the subjects and teachers of their own coordination (D69)."""
    user = user_with(Profile.COORDINATOR, ScopeKind.COORDINATION, C1)
    assert reg.can(user, "x.read_all") is True
    assert reg.can_on_coordination(user, "x.write", C3) is False
    assert reg.can_on_coordination(user, "x.write", C1) is True


def test_other_profiles_do_not_get_the_coordinators_global_read(world, reg):
    """The unscoped read is registered for the coordinator only."""
    for profile in (Profile.PGC_MANAGER, Profile.EXECUTIVE_BOARD, Profile.TEACHER):
        user = user_with(profile, ScopeKind.NONE, None, username=f"u_{profile}")
        assert reg.can(user, "x.read_all") is False


def test_the_same_number_as_another_scope_kind_never_matches(world, reg):
    """C1 has the id 20 like F2 and T1: neither a Faculty nor a teacher 20 gives C1."""
    teacher_user = user_with(Profile.TEACHER, ScopeKind.TEACHER, T1, "t")
    viewer = user_with(Profile.VIEWER, ScopeKind.NONE, None, "v")
    wrong_kind = user_with(Profile.COORDINATOR, ScopeKind.FACULTY, C1, "c")
    for user in (teacher_user, viewer, wrong_kind):
        assert not reg.can_on_coordination(user, "x.read", C1)
        assert reg.coordination_ids(user, "x.read") == set()


def test_admin_flags_give_no_access(world, reg):
    """Superuser and staff flags without a role open nothing (D39)."""
    root = get_user_model().objects.create_superuser(username="root", password="x")
    staff = get_user_model().objects.create_user(username="st", password="x", is_staff=True)
    for user in (root, staff):
        assert not reg.can_on_coordination(user, "x.write", C1)
        assert reg.coordination_ids(user, "x.write") == set()
        assert reg.own_teacher_ids(user, "x.read") == set()


def test_a_superuser_who_is_coordinator_reaches_only_their_coordination(world, reg):
    """The flag adds nothing to a real role."""
    user = user_with(Profile.COORDINATOR, ScopeKind.COORDINATION, C1)
    user.is_superuser = True
    user.save()
    assert reg.can_on_coordination(user, "x.write", C1)
    assert not reg.can_on_coordination(user, "x.write", C3)


def test_anonymous_and_inactive_users_get_nothing(world, reg):
    """No session, or a disabled account, fails closed."""
    inactive = user_with(Profile.PGC_MANAGER, ScopeKind.FACULTY, F1)
    inactive.is_active = False
    inactive.save()
    for user in (AnonymousUser(), inactive):
        assert not reg.can_on_coordination(user, "x.write", C1)
        assert reg.coordination_ids(user, "x.write") == set()
        assert reg.own_teacher_ids(user, "x.read") == set()


def test_a_revoked_role_stops_working_at_once(world, reg):
    """Deleting the assignment (how a role is revoked, D62) removes the access."""
    user = user_with(Profile.COORDINATOR, ScopeKind.COORDINATION, C1)
    assert reg.can_on_coordination(user, "x.write", C1)
    user.role_assignments.all().delete()
    assert not reg.can_on_coordination(user, "x.write", C1)
    assert reg.coordination_ids(user, "x.write") == set()


def test_several_roles_add_up_and_no_more(world, reg):
    """A coordinator of C1 who is also a teacher reaches C1 and their own record only."""
    user = user_with(Profile.COORDINATOR, ScopeKind.COORDINATION, C1)
    RoleAssignment.objects.create(
        user=user, profile=Profile.TEACHER, scope_kind=ScopeKind.TEACHER, scope_id=T1
    )
    assert reg.coordination_ids(user, "x.read") == {C1}
    assert reg.own_teacher_ids(user, "x.read") == {T1}
    assert not reg.can_on_coordination(user, "x.read", C2)


def test_a_coordinator_of_a_coordination_in_another_faculty_gets_nothing_here(world, reg):
    """A coordinator of C3 (F2) reaches nothing of F1."""
    user = user_with(Profile.COORDINATOR, ScopeKind.COORDINATION, C3)
    assert not any(reg.can_on_coordination(user, "x.write", c) for c in (C1, C2))


def test_moving_a_coordination_to_another_faculty_moves_the_access_with_it(world, reg):
    """The Faculty is read at check time, so the old manager loses and the new one gains (D62)."""
    old = user_with(Profile.PGC_MANAGER, ScopeKind.FACULTY, F1, "old")
    new = user_with(Profile.PGC_MANAGER, ScopeKind.FACULTY, F2, "new")
    assert reg.can_on_coordination(old, "x.write", C1)
    assert not reg.can_on_coordination(new, "x.write", C1)
    Coordination.objects.filter(pk=C1).update(faculty_id=F2)
    assert not reg.can_on_coordination(old, "x.write", C1)
    assert reg.can_on_coordination(new, "x.write", C1)


@pytest.mark.parametrize("target", [None, 987654])
def test_an_empty_or_unknown_coordination_is_refused(world, reg, target):
    """A missing or deleted coordination fails closed instead of raising or matching."""
    user = user_with(Profile.PGC_MANAGER, ScopeKind.FACULTY, F1)
    assert reg.can_on_coordination(user, "x.write", target) is False


def test_an_unscoped_or_unknown_action_is_a_programming_error(world, reg):
    """An unscoped action cannot be checked against a coordination, and unknown codes fail."""
    user = user_with(Profile.PGC_MANAGER, ScopeKind.FACULTY, F1)
    with pytest.raises(ImproperlyConfigured):
        reg.can_on_coordination(user, "x.unscoped_write", C1)
    with pytest.raises(ImproperlyConfigured):
        reg.coordination_ids(user, "x.unscoped_write")
    with pytest.raises(LookupError):
        reg.can_on_coordination(user, "x.missing", C1)


def test_require_on_coordination_raises_permission_denied(world, reg):
    """The requiring form gives a 403 on denial and returns quietly otherwise."""
    from django.core.exceptions import PermissionDenied

    user = user_with(Profile.COORDINATOR, ScopeKind.COORDINATION, C1)
    reg.require_on_coordination(user, "x.write", C1)
    with pytest.raises(PermissionDenied):
        reg.require_on_coordination(user, "x.write", C2)


def test_the_checks_use_a_fixed_small_number_of_queries(world, reg, django_assert_max_num_queries):
    """No query per coordination: at most two queries per call."""
    user = user_with(Profile.PGC_MANAGER, ScopeKind.FACULTY, F1)
    with django_assert_max_num_queries(2):
        reg.can_on_coordination(user, "x.write", C1)
    with django_assert_max_num_queries(2):
        reg.coordination_ids(user, "x.write")


# --- the teacher reads only what is theirs (D09) ---------------------------------------------


def test_own_teacher_ids_are_those_of_the_users_teacher_assignments(world, reg):
    """The teacher profile yields the teacher records linked to the account."""
    user = user_with(Profile.TEACHER, ScopeKind.TEACHER, T1)
    assert reg.own_teacher_ids(user, "x.read") == {T1}


def test_own_teacher_ids_ignore_other_profiles_and_wrong_kinds(world, reg):
    """Only the teacher profile, with a teacher scope, counts; a wrong-kind row is ignored."""
    coordinator = user_with(Profile.COORDINATOR, ScopeKind.COORDINATION, C1, "c")
    odd = user_with(Profile.TEACHER, ScopeKind.COORDINATION, C1, "o")
    assert reg.own_teacher_ids(coordinator, "x.read") == set()
    assert reg.own_teacher_ids(odd, "x.read") == set()


def test_own_teacher_ids_are_empty_when_the_action_does_not_admit_teachers(world, reg):
    """A write action never admits the teacher, so nothing is theirs there."""
    user = user_with(Profile.TEACHER, ScopeKind.TEACHER, T1)
    assert reg.own_teacher_ids(user, "x.write") == set()


def test_a_teacher_reads_their_own_record_and_no_other(world, reg):
    """T1's account reads T1 and not T2, even though both exist (D09)."""
    user = user_with(Profile.TEACHER, ScopeKind.TEACHER, T1)
    assert reg.can_on_teacher(user, "x.read", Teacher.objects.get(pk=T1)) is True
    assert reg.can_on_teacher(user, "x.read", Teacher.objects.get(pk=T2)) is False


def test_a_teacher_never_writes_even_on_their_own_record(world, reg):
    """No write action admits the teacher profile."""
    user = user_with(Profile.TEACHER, ScopeKind.TEACHER, T1)
    assert reg.can_on_teacher(user, "x.write", Teacher.objects.get(pk=T1)) is False


def test_a_coordinator_acts_on_the_teachers_of_their_coordination_only(world, reg):
    """Coordinator of C1: T1 (C1) yes, T2 (C3) no; a manager of F2 reaches T2 and not T1."""
    coordinator = user_with(Profile.COORDINATOR, ScopeKind.COORDINATION, C1, "c")
    manager = user_with(Profile.PGC_MANAGER, ScopeKind.FACULTY, F2, "m")
    t1, t2 = Teacher.objects.get(pk=T1), Teacher.objects.get(pk=T2)
    assert reg.can_on_teacher(coordinator, "x.write", t1) is True
    assert reg.can_on_teacher(coordinator, "x.write", t2) is False
    assert reg.can_on_teacher(manager, "x.write", t2) is True
    assert reg.can_on_teacher(manager, "x.write", t1) is False
