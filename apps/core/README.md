# core

**Responsibility:** users, profiles, scopes (Faculty, coordination, teacher), server-side permission checks and the generic audit log.

**Main models:**
- `User`: custom user model (`AUTH_USER_MODEL`).
- `RoleAssignment`: one profile held by a user over one scope (`scope_kind` + `scope_id`). The scope id is a plain number until Faculty, coordination and teacher exist (T2.1, T3.1). See D38.

**Domain rules:** `roles.py` holds the profiles, scope kinds and which scope kind each profile admits (no dependency on views or models).

**Permissions:** `permissions.py` is a registry of actions (`registry.register(code, profiles, write=...)`) with `can(user, action, scope_kind, scope_id)` and `require(...)` (raises `PermissionDenied`); `mixins.PermissionRequiredMixin` enforces it in views. Superuser flag gives no business access. See D39.

**Audit:** `AuditEntry` is an append-only log (actor, time, entity, previous/new values, reason). Write business data with `audit.audited_save(instance, actor, reason)` and `audit.audited_delete(instance, actor, reason)`, which log in the same transaction; a reason is required for updates and deletes. See D40.

**Authentication:** `identity.py` defines the `IdentityProvider` contract, the development-only `LocalIdentityProvider` and `IdentityProviderBackend` (the Django backend that delegates to the provider in `AUTH_IDENTITY_PROVIDER`). `checks.py` fails startup on an unknown provider (`core.E001`) or local login in production (`core.E002`). LDAP/SSO is an open question. See D41.

**Screens:** `generic.py` has the shared list/create/edit/delete views (login, permission, audit, mandatory reason, 25 per page); `templatetags/pgc_permissions.py` provides `{% can "action" as ok %}` to hide links (the server still checks). `templates/base.html` is the layout. `Scoped*` views (D51) show and accept only the scopes the user manages (`registry.scope_ids`). `Parameter` (code, name, positive value) holds the system parameters that the PGC manager can change at `/core/parameters/` (permission `parameter.edit`); `parameters.get_parameter(code)` reads one and fails closed if it is missing. `semester_weeks` (15) is loaded by migration 0005. See D60. `scopes.py` resolves a scope to its Faculty (resolvers are registered by `academic` and `staff`); `accounts.py` has the services that create accounts and assign or revoke roles with the authority checks of D62; screens at `/core/accounts/` (list, create, edit, deactivate/activate; no password is ever asked for or shown); the operator command `manage.py grant_role <username> <profile> <scope_kind> [<scope_id>]` grants any profile, including the first PGC manager. The reason fields (D59) offer a list of usual reasons plus optional free text; the audit entry stores the text. See D50.

**Dependencies:** none. Every other app may depend on `core`.
