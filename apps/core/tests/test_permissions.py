"""Tests for the server-side permission layer.

Implements: docs/especificacao/07_arquitetura.md – Permissions (checked on the server).
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.test import RequestFactory
from django.views import View

from apps.core.mixins import PermissionRequiredMixin
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.core.permissions import PermissionRegistry, can, require

User = get_user_model()

ALL_PROFILES = list(Profile)


def make_user(profile, scope_kind=ScopeKind.NONE, scope_id=None, username="u"):
    """Create a user holding a single role assignment."""
    user = User.objects.create_user(username=username, password="x")
    RoleAssignment.objects.create(
        user=user, profile=profile, scope_kind=scope_kind, scope_id=scope_id
    )
    return user


@pytest.mark.django_db
@pytest.mark.parametrize("profile", ALL_PROFILES)
def test_only_facilities_can_edit_rooms(profile):
    """Património is the only profile that enters and edits rooms."""
    user = make_user(profile)
    assert can(user, "room.edit") is (profile == Profile.FACILITIES)


@pytest.mark.django_db
@pytest.mark.parametrize("profile", ALL_PROFILES)
def test_only_academic_services_can_edit_enrollments(profile):
    """Serviços Académicos are the only profile that enters enrollments."""
    user = make_user(profile)
    assert can(user, "enrollment.edit") is (profile == Profile.ACADEMIC_SERVICES)


@pytest.mark.django_db
@pytest.mark.parametrize("profile", [Profile.VIEWER, Profile.TEACHER])
def test_read_only_profiles_never_pass_a_write_action(profile):
    """Viewer and teacher are read-only: no registered write action admits them."""
    user = make_user(profile)
    assert not can(user, "room.edit")
    assert not can(user, "enrollment.edit")


def test_registry_refuses_to_grant_a_write_action_to_a_read_only_profile():
    """Registering a write action for viewer or teacher is a programming error."""
    registry = PermissionRegistry()
    with pytest.raises(ValueError):
        registry.register("thing.edit", {Profile.VIEWER}, write=True)
    with pytest.raises(ValueError):
        registry.register("thing.edit", {Profile.TEACHER}, write=True)


def test_registry_refuses_to_register_the_same_action_twice():
    """An action code has a single definition."""
    registry = PermissionRegistry()
    registry.register("thing.view", {Profile.VIEWER}, write=False)
    with pytest.raises(ValueError):
        registry.register("thing.view", {Profile.VIEWER}, write=False)


@pytest.mark.django_db
def test_unknown_action_fails_closed():
    """Asking about an unregistered action raises instead of silently allowing."""
    user = make_user(Profile.FACILITIES)
    with pytest.raises(LookupError):
        can(user, "does.not.exist")


def test_anonymous_user_is_always_denied():
    """Anonymous users pass nothing."""
    assert can(AnonymousUser(), "room.edit") is False


@pytest.mark.django_db
def test_inactive_user_is_always_denied():
    """A deactivated account loses every permission, whatever its assignments."""
    user = make_user(Profile.FACILITIES)
    user.is_active = False
    user.save()
    assert can(user, "room.edit") is False


@pytest.mark.django_db
def test_superuser_flag_does_not_bypass_the_specification():
    """is_superuser is maintenance-only and grants no business permission (decision D39)."""
    user = User.objects.create_superuser(username="root", password="x")
    assert can(user, "room.edit") is False


@pytest.mark.django_db
def test_permissions_of_several_profiles_add_up():
    """A user holding two profiles can do what either allows."""
    user = make_user(Profile.FACILITIES)
    RoleAssignment.objects.create(
        user=user, profile=Profile.ACADEMIC_SERVICES, scope_kind=ScopeKind.NONE, scope_id=None
    )
    assert can(user, "room.edit") and can(user, "enrollment.edit")


@pytest.mark.django_db
def test_scoped_check_requires_the_exact_scope():
    """With a scope, the assignment must match kind and id exactly (hierarchy comes in T2.1)."""
    registry = PermissionRegistry()
    registry.register("dsd.edit", {Profile.COORDINATOR}, write=True, scoped=True)
    user = make_user(Profile.COORDINATOR, ScopeKind.COORDINATION, 3)
    assert registry.can(user, "dsd.edit", ScopeKind.COORDINATION, 3) is True
    assert registry.can(user, "dsd.edit", ScopeKind.COORDINATION, 4) is False
    assert registry.can(user, "dsd.edit", ScopeKind.FACULTY, 3) is False


@pytest.mark.django_db
def test_manager_with_two_faculties_can_act_on_each_but_not_on_others():
    """The PGC manager acts only on the Faculties assigned to them."""
    registry = PermissionRegistry()
    registry.register("subject.edit", {Profile.PGC_MANAGER}, write=True, scoped=True)
    user = make_user(Profile.PGC_MANAGER, ScopeKind.FACULTY, 1)
    RoleAssignment.objects.create(
        user=user, profile=Profile.PGC_MANAGER, scope_kind=ScopeKind.FACULTY, scope_id=2
    )
    assert registry.can(user, "subject.edit", ScopeKind.FACULTY, 1)
    assert registry.can(user, "subject.edit", ScopeKind.FACULTY, 2)
    assert not registry.can(user, "subject.edit", ScopeKind.FACULTY, 3)


@pytest.mark.django_db
def test_right_scope_with_the_wrong_profile_is_denied():
    """Matching the scope is not enough: the profile must be allowed for the action."""
    registry = PermissionRegistry()
    registry.register("dsd.edit", {Profile.COORDINATOR}, write=True, scoped=True)
    user = make_user(Profile.VIEWER, ScopeKind.COORDINATION, 3)
    assert registry.can(user, "dsd.edit", ScopeKind.COORDINATION, 3) is False


@pytest.mark.django_db
def test_scoped_action_checked_without_a_scope_fails_closed_instead_of_passing():
    """A scoped action never passes 'for any scope': omitting the scope is a configuration error.

    Otherwise a coordinator of coordination 3 could act on every coordination whenever a view
    forgets to say which one it concerns.
    """
    registry = PermissionRegistry()
    registry.register("dsd.edit", {Profile.COORDINATOR}, write=True, scoped=True)
    user = make_user(Profile.COORDINATOR, ScopeKind.COORDINATION, 3)
    with pytest.raises(ImproperlyConfigured):
        registry.can(user, "dsd.edit")
    with pytest.raises(ImproperlyConfigured):
        registry.require(user, "dsd.edit")


@pytest.mark.django_db
def test_view_mixin_with_a_scoped_action_requires_a_scope_override():
    """A view for a scoped action that does not override get_permission_scope is rejected."""
    registry = PermissionRegistry()
    registry.register("dsd.edit", {Profile.COORDINATOR}, write=True, scoped=True)

    class ScopedView(PermissionRequiredMixin, View):
        permission_action = "dsd.edit"
        permission_registry = registry

        def get(self, request):
            from django.http import HttpResponse

            return HttpResponse("ok")

    request = RequestFactory().get("/")
    request.user = make_user(Profile.COORDINATOR, ScopeKind.COORDINATION, 3)
    with pytest.raises(ImproperlyConfigured):
        ScopedView.as_view()(request)


@pytest.mark.django_db
def test_require_raises_permission_denied():
    """require() turns a denial into Django's PermissionDenied (HTTP 403)."""
    user = make_user(Profile.VIEWER)
    with pytest.raises(PermissionDenied):
        require(user, "room.edit")
    require(make_user(Profile.FACILITIES, username="p"), "room.edit")


class _RoomEditView(PermissionRequiredMixin, View):
    permission_action = "room.edit"

    def get(self, request):
        from django.http import HttpResponse

        return HttpResponse("ok")


@pytest.mark.django_db
def test_view_mixin_denies_without_permission_and_allows_with_it():
    """The view mixin enforces the check on the server for every request."""
    factory = RequestFactory()

    request = factory.get("/")
    request.user = make_user(Profile.VIEWER)
    with pytest.raises(PermissionDenied):
        _RoomEditView.as_view()(request)

    request = factory.get("/")
    request.user = make_user(Profile.FACILITIES, username="p")
    assert _RoomEditView.as_view()(request).status_code == 200
