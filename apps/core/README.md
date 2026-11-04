# core

**Responsibility:** users, profiles, scopes (Faculty, coordination, teacher), server-side permission checks and the generic audit log.

**Main models:**
- `User`: custom user model (`AUTH_USER_MODEL`).
- `RoleAssignment`: one profile held by a user over one scope (`scope_kind` + `scope_id`). The scope id is a plain number until Faculty, coordination and teacher exist (T2.1, T3.1). See D38.

**Domain rules:** `roles.py` holds the profiles, scope kinds and which scope kind each profile admits (no dependency on views or models).

**Permissions:** `permissions.py` is a registry of actions (`registry.register(code, profiles, write=...)`) with `can(user, action, scope_kind, scope_id)` and `require(...)` (raises `PermissionDenied`); `mixins.PermissionRequiredMixin` enforces it in views. Superuser flag gives no business access. See D39.

**Planned:** audit entry (T1.3).

**Dependencies:** none. Every other app may depend on `core`.
