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
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def membership_has_permission(membership, permission_key: str) -> bool:
    """Return ``True`` if ``membership`` carries ``permission_key``.

    Safe to call with a ``None`` membership — returns ``False``. Resolution
    short-circuits on first match, so the per-user / per-group grant
    queries only run when the role bundle doesn't already cover the key.
    """
    if membership is None or not permission_key:
        return False

    if _role_covers(membership, permission_key):
        return True

    return _grants_cover(membership, permission_key)


def _role_covers(membership, permission_key: str) -> bool:
    """Check the role bundle — FK first, legacy string as fallback."""
    role_permissions = _resolve_role_permissions(membership)
    return permission_key in role_permissions


def _resolve_role_permissions(membership) -> set[str]:
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

    from infrastructure.persistence.workspaces.models import WorkspaceRole

    system_role = (
        WorkspaceRole.objects
        .filter(workspace__isnull=True, is_system=True, slug=legacy_role)
        .only("permissions")
        .first()
    )
    if system_role is None:
        logger.warning(
            "membership_permission legacy_role_unresolved membership_id=%s role=%s",
            getattr(membership, "id", None),
            legacy_role,
        )
        return set()
    return set(system_role.permissions or [])


def _grants_cover(membership, permission_key: str) -> bool:
    """Check direct-user and group-mediated permission grants."""
    from infrastructure.persistence.workspaces.models import (
        WorkspaceGroupMembership,
        WorkspacePermissionGrant,
    )

    workspace_id = getattr(membership, "workspace_id", None)
    user_id = getattr(membership, "user_id", None)
    if workspace_id is None or user_id is None:
        return False

    if WorkspacePermissionGrant.objects.filter(
        workspace_id=workspace_id,
        user_id=user_id,
        permission_key=permission_key,
    ).exists():
        return True

    user_group_ids = WorkspaceGroupMembership.objects.filter(
        user_id=user_id,
        group__workspace_id=workspace_id,
    ).values_list("group_id", flat=True)

    if not user_group_ids:
        return False

    return WorkspacePermissionGrant.objects.filter(
        workspace_id=workspace_id,
        group_id__in=list(user_group_ids),
        permission_key=permission_key,
    ).exists()
