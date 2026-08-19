"""Membership-scoped DRF permission classes.

The new capability-backed gate (``has_workspace_permission(key)``)
lives here because permissions are membership-domain per ADR 0002 — a
user with no workspace membership has no permissions. This module
deliberately does NOT import from ``components.workspace.api`` so the
cross-context boundary stays clean.

Workspace resolution (extracting the active workspace from URL kwargs,
request body, nested lookups) is duplicated here in a trimmed form
rather than inherited from ``IsOrgOwnerOrMember``. The duplication is
small (<80 LOC) and worth it to keep the dependency graph pointing
the right way.
"""

from __future__ import annotations

import json

from rest_framework import permissions
from rest_framework.exceptions import UnsupportedMediaType


def _get_workspace_models():
    from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

    _wsp = get_workspaces_models_provider()
    Workspace = _wsp.Workspace
    WorkspaceMembership = _wsp.WorkspaceMembership

    return Workspace, WorkspaceMembership


def _get_team_models():
    from components.team.application.providers.team_models_provider import get_team_models_provider

    Team = get_team_models_provider().Team
    TeamMembership = get_team_models_provider().TeamMembership

    return Team, TeamMembership


def _safe_request_data(request):
    try:
        return getattr(request, "data", {}) or {}
    except UnsupportedMediaType:
        body = getattr(request, "body", b"") or b""
        if not body:
            return {}
        content_type = getattr(request, "content_type", "") or ""
        if "json" not in content_type:
            return {}
        encoding = getattr(request, "encoding", None) or "utf-8"
        try:
            return json.loads(body.decode(encoding))
        except (TypeError, ValueError, UnicodeDecodeError):
            return {}


_WORKSPACE_LOOKUP_KEYS = (
    "workspace_id",
    "workspace",
    "workspaceId",
    "workspace_pk",
)


def user_is_active_workspace_member(user, workspace_id) -> bool:
    """True if ``user`` owns or holds an ACTIVE membership in ``workspace_id``.

    Object-level helper for published, workspace-wide content reads (e.g.
    a SENT newsletter) where membership itself — any role, sponsor/viewer
    included — is the gate, not a permission-bundle key.
    """
    if not getattr(user, "is_authenticated", False) or not workspace_id:
        return False
    Workspace, WorkspaceMembership = _get_workspace_models()
    try:
        if Workspace.objects.filter(id=workspace_id, workspace_owner_id=user.id).exists():
            return True
        return WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user=user,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists()
    except (ValueError, TypeError):
        return False


def resolve_workspace_membership_gate(user, workspace):
    """Resolve the ``WorkspaceMembership`` half of an authorization decision.

    Returns ``(active_membership, team_fallback_allowed)``:

    - ``active_membership`` — the user's ACTIVE membership row on ``workspace``
      (a support-impersonation row counts, by design), or ``None``.
    - ``team_fallback_allowed`` — whether the caller may fall through to the
      pre-Phase-3b team-only compatibility fallback. ``False`` whenever a
      membership row EXISTS but is not ACTIVE.

    **A membership row is authoritative.** Revocation (``DELETE
    /workspaces/<ws>/members/<user>/``) soft-flips the row to ``SUSPENDED`` and
    deliberately leaves the person on the workspace's teams so re-inviting them
    restores their history. Before this helper, both capability gates read that
    as "this user has no membership row" and fell through to the team fallback,
    which hands any active team member the seeded ``member`` bundle — including
    ``manage_findings``. A removed member could still suppress findings. The
    fallback exists for the un-backfilled legacy shape (a team member with NO
    membership row at all); it must never override an explicit revocation.

    ONE query, shared by every gate so the invariant cannot drift between them.
    """
    _, WorkspaceMembership = _get_workspace_models()
    memberships = list(
        WorkspaceMembership.objects.filter(workspace=workspace, user=user).select_related("workspace_role")
    )
    active = next(
        (row for row in memberships if row.status == WorkspaceMembership.Status.ACTIVE),
        None,
    )
    if active is not None:
        return active, False
    return None, not memberships


def is_workspace_owner(user, workspace_id) -> bool:
    """True if ``user`` is the OWNER of ``workspace_id`` (org owner) — stricter than
    membership. Used to gate owner-only actions (e.g. the sample-data-mode toggle)."""
    if not getattr(user, "is_authenticated", False) or not workspace_id:
        return False
    Workspace, _ = _get_workspace_models()
    try:
        return Workspace.objects.filter(id=workspace_id, workspace_owner_id=user.id).exists()
    except (ValueError, TypeError):
        return False


class IsWorkspaceOwner(permissions.BasePermission):
    """Allows ONLY the workspace owner. Resolves ``workspace_id`` from the URL kwargs."""

    message = "Only the workspace owner may perform this action."

    def has_permission(self, request, view) -> bool:
        kwargs = getattr(view, "kwargs", None) or {}
        workspace_id = kwargs.get("workspace_id") or kwargs.get("workspace")
        return is_workspace_owner(getattr(request, "user", None), workspace_id)


class IsActiveWorkspaceMember(permissions.BasePermission):
    """Allows the workspace owner or any ACTIVE member. Resolves the workspace
    from the URL kwargs. The membership floor for workspace-scoped reads that
    carry no capability of their own (e.g. the setup-status funnel)."""

    message = "You must be a member of this workspace."

    def has_permission(self, request, view) -> bool:
        kwargs = getattr(view, "kwargs", None) or {}
        workspace_id = next(
            (kwargs[key] for key in _WORKSPACE_LOOKUP_KEYS if kwargs.get(key)),
            None,
        )
        return user_is_active_workspace_member(getattr(request, "user", None), workspace_id)


def _resolve_workspace(request, view):
    """Find the active workspace from URL kwargs, request body, or profile.

    Trimmed copy of the logic in ``IsOrgOwnerOrMember._resolve_workspace``.
    Returns a ``Workspace`` or ``None``.
    """
    Workspace, _ = _get_workspace_models()

    sources = []
    parser_context = getattr(request, "parser_context", None) or {}
    kwargs = parser_context.get("kwargs") or {}
    if kwargs:
        sources.append(kwargs)
    view_kwargs = getattr(view, "kwargs", None) or {}
    if view_kwargs:
        sources.append(view_kwargs)
    data = _safe_request_data(request)
    if data:
        sources.append(data)
    query_params = getattr(request, "query_params", None)
    if query_params:
        sources.append(query_params)

    for source in sources:
        for key in _WORKSPACE_LOOKUP_KEYS:
            value = source.get(key) if hasattr(source, "get") else None
            if value:
                try:
                    workspace = Workspace.objects.filter(id=value).first()
                except (ValueError, TypeError):
                    continue
                if workspace:
                    return workspace

    # Fall back to the user's active workspace if one is stored on their
    # profile. Mirrors what the request middleware uses.
    profile = getattr(getattr(request, "user", None), "profile", None)
    if profile and getattr(profile, "active_workspace_id", None):
        try:
            return Workspace.objects.filter(id=profile.active_workspace_id).first()
        except (ValueError, TypeError):
            return None
    return None


def _has_object_lookup(request, view) -> bool:
    """Return True when the view has an object lookup kwarg populated.

    Lets has_permission defer the final decision to has_object_permission
    on detail endpoints (``/<model>/<id>/``) where workspace is resolved
    from the fetched object rather than the URL.
    """
    lookup_field = getattr(view, "lookup_field", None) or "pk"
    lookup_url_kwarg = getattr(view, "lookup_url_kwarg", None)
    lookup_keys = [key for key in [lookup_url_kwarg, lookup_field] if key]

    parser_context = getattr(request, "parser_context", None) or {}
    kwargs = parser_context.get("kwargs", {}) or {}
    for key in lookup_keys:
        if kwargs.get(key):
            return True
    view_kwargs = getattr(view, "kwargs", {}) or {}
    for key in lookup_keys:
        if view_kwargs.get(key):
            return True
    return False


class _HasWorkspacePermissionBase(permissions.BasePermission):
    """Base class — subclass via :func:`has_workspace_permission` to set ``permission_key``.

    Resolution order (short-circuits on first allow):

    1. ``is_staff`` or ``is_superuser`` — allowed.
    2. Workspace owner (structural, pre-RBAC) — allowed.
    3. Active ``WorkspaceMembership`` whose role (or per-user/group grant)
       carries the permission key — allowed.
    4. A membership row that exists but is NOT active (revoked/suspended,
       invited, pending approval) — denied outright. An explicit
       revocation is authoritative; step 5 is never reached.
    5. Team-only compatibility fallback (pre-Phase-3b) — allowed if the
       user has NO membership row at all, has an active team membership,
       and the seeded ``member`` role carries the key.
    6. Otherwise — denied.
    """

    permission_key: str = ""
    message = "You do not have permission to perform this action in this workspace."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        workspace = _resolve_workspace(request, view)
        if workspace is None:
            if _has_object_lookup(request, view):
                return True
            self.message = "Workspace identifier is required for this action."
            return False

        return self._membership_authorizes(user, workspace)

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        Workspace, _ = _get_workspace_models()
        workspace = None
        if isinstance(obj, Workspace):
            workspace = obj
        elif hasattr(obj, "workspace") and getattr(obj, "workspace", None) is not None:
            workspace = obj.workspace
        elif hasattr(obj, "workspace_id") and getattr(obj, "workspace_id", None):
            workspace = Workspace.objects.filter(id=obj.workspace_id).first()

        if workspace is None:
            workspace = _resolve_workspace(request, view)
        if workspace is None:
            return False

        return self._membership_authorizes(user, workspace)

    def _membership_authorizes(self, user, workspace) -> bool:
        if str(workspace.workspace_owner_id) == str(user.id):
            return True

        membership, team_fallback_allowed = resolve_workspace_membership_gate(user, workspace)
        if membership is not None:
            from components.membership.application.services.membership_permission_service import (
                membership_has_permission,
            )

            return membership_has_permission(membership, self.permission_key)

        if not team_fallback_allowed:
            # A revoked/suspended membership is an authoritative DENY.
            return False

        return self._team_member_has_permission_via_member_role(user, workspace)

    def _team_member_has_permission_via_member_role(self, user, workspace) -> bool:
        Team, _ = _get_team_models()
        if not Team.objects.filter(
            workspace=workspace,
            status=Team.ACTIVE,
            members__id=user.id,
        ).exists():
            return False

        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

        WorkspaceRole = get_workspaces_models_provider().WorkspaceRole

        member_role = (
            WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug="member")
            .only("permissions")
            .first()
        )
        if member_role is None:
            return False
        return self.permission_key in (member_role.permissions or [])


def has_workspace_permission(permission_key: str):
    """Return a DRF permission class gating on ``permission_key``.

    Usage::

        permission_classes = (has_workspace_permission("manage_budgets"),)

    Manufactures a named subclass per key so DRF's default
    ``permission_denied`` debug output shows which key was required —
    cheaper to debug than a generic "permission denied" message.
    """
    if not permission_key or not isinstance(permission_key, str):
        raise ValueError("has_workspace_permission requires a non-empty permission key")

    class _HasPermission(_HasWorkspacePermissionBase):
        pass

    _HasPermission.permission_key = permission_key
    _HasPermission.__name__ = f"HasWorkspacePermission_{permission_key}"
    _HasPermission.__qualname__ = _HasPermission.__name__
    return _HasPermission
