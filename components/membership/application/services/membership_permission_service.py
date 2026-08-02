"""Answer "does this membership carry permission X?" — Phase 2 of the role redesign.

This is the single resolver every authorization gate should call when
deciding whether a workspace membership covers a given permission key.
It combines three grant sources, in priority order:

1. **Role permissions** — read from the ``workspace_role`` FK if set;
   otherwise fall back to the legacy ``role`` string and look up the
   matching seeded system role. The fallback exists only while Phase 1c
   is rolling out — once every membership row carries ``workspace_role``
   we can drop it (Phase 3).
2. **Direct user grants** — a ``WorkspacePermissionGrant`` row keyed on
   ``(workspace, user, permission_key)``. Grants are the escape hatch for
   "give Bob this one capability without promoting his role."
3. **Group grants** — permission grants attached to a
   ``WorkspaceGroup`` that the user belongs to.

**What this function does NOT check**: workspace ownership. Ownership is
structural — a single row on ``Workspace.workspace_owner_id`` — and
should be short-circuited by the caller (the DRF permission class). That
keeps this function a pure "does the role+grants bundle cover the
key" question without conflating it with the separate "is this the
person who created the workspace" question.

**Persistence access goes through a port.** The three grant sources live on
the ``workspaces`` persistence app, which this application-layer resolver must
NOT import (architecture-manifesto Rule 2 — the application layer reaches
persistence through a port, never the ORM). The reads are served by
:class:`RolePermissionsReadPort`; the ``membership`` argument is a boundary
object supplied by the caller (a DRF permission class / controller), and only
its plain attributes (``workspace_role`` permissions, ``role``, ``workspace_id``,
``user_id``) are read here — no query is issued from this module. The port is
injected; ``None`` (the default) resolves the ORM-backed adapter lazily via the
membership provider so existing callers keep the two-argument call site.
"""

from __future__ import annotations

import logging

from components.membership.application.ports.role_permissions_read_port import (
    RolePermissionsReadPort,
)

logger = logging.getLogger(__name__)


def membership_has_permission(
    membership,
    permission_key: str,
    *,
    role_permissions_reader: RolePermissionsReadPort | None = None,
) -> bool:
    """Return ``True`` if ``membership`` carries ``permission_key``.

    Safe to call with a ``None`` membership — returns ``False``. Resolution
    short-circuits on first match, so the per-user / per-group grant
    queries only run when the role bundle doesn't already cover the key.

    ``role_permissions_reader`` is the port that serves the RBAC reads; when
    omitted it is resolved from the membership provider (composition root), so
    the common call site stays ``membership_has_permission(membership, key)``.
    """
    if membership is None or not permission_key:
        return False

    reader = role_permissions_reader or _default_reader()

    if _role_covers(membership, permission_key, reader):
        return True

    return _grants_cover(membership, permission_key, reader)


def _default_reader() -> RolePermissionsReadPort:
    from components.membership.application.providers.membership_provider import (
        MembershipProvider,
    )

    return MembershipProvider().build_role_permissions_reader()


def _role_covers(membership, permission_key: str, reader: RolePermissionsReadPort) -> bool:
    """Check the role bundle — FK first, legacy string as fallback."""
    role_permissions = _resolve_role_permissions(membership, reader)
    return permission_key in role_permissions


def _resolve_role_permissions(membership, reader: RolePermissionsReadPort) -> set[str]:
    """Return the set of permission keys on the membership's role.

    Prefers the ``workspace_role`` FK (Phase 1b onward). Falls back to
    the legacy ``role`` string so pre-Phase-1b rows still authorize
    correctly through the migration window.
    """
    workspace_role = getattr(membership, "workspace_role", None)
    if workspace_role is not None:
        return set(workspace_role.permissions or [])

    legacy_role = getattr(membership, "role", None) or ""
    if not legacy_role:
        return set()

    system_role = reader.get_system_role_permissions(legacy_role)
    if system_role is None:
        logger.warning(
            "membership_permission legacy_role_unresolved membership_id=%s role=%s",
            getattr(membership, "id", None),
            legacy_role,
        )
        return set()
    return set(system_role.permission_keys)


def _grants_cover(membership, permission_key: str, reader: RolePermissionsReadPort) -> bool:
    """Check direct-user and group-mediated permission grants."""
    workspace_id = getattr(membership, "workspace_id", None)
    user_id = getattr(membership, "user_id", None)
    if workspace_id is None or user_id is None:
        return False

    return reader.has_grant(
        workspace_id=workspace_id,
        user_id=user_id,
        permission_key=permission_key,
    )
