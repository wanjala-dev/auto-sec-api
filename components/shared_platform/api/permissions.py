"""Consolidated permission classes for shared_platform component.

This module consolidates permission classes from:
- contact_permissions: IsLoggedInUserOrAdmin, IsAdminUser
- core_permissions: IsOwnerOrReadOnly, RequiresFeatureFlag
- upload_permissions: IsOwnerOrReadOnly
- workspace membership: HasWorkspaceMembership, HasWorkspaceRole

See ``docs/adr/0002-personas-and-rbac.md`` — permission decisions read
``WorkspaceMembership.role`` only. Persona is for experience routing and
must NEVER be used in a permission check.
"""

from rest_framework import permissions


# =============================================================================
# CONTACT PERMISSIONS
# =============================================================================

class IsLoggedInUserOrAdmin(permissions.BasePermission):
    """Allow access if user is the object owner or is admin staff."""

    def has_object_permission(self, request, view, obj):
        return obj == request.user or request.user.is_staff


class IsAdminUser(permissions.BasePermission):
    """Allow access only to admin/staff users."""

    def has_permission(self, request, view):
        return request.user and request.user.is_staff

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_staff


# =============================================================================
# CORE (FEATURE FLAGS) PERMISSIONS
# =============================================================================

class IsOwnerOrReadOnly(permissions.BasePermission):
    """Allow write access only to object owner; others can read."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.owner == request.user


class RequiresFeatureFlag(permissions.BasePermission):
    """
    Require a named feature flag to be enabled for this request.

    Usage (CBV):
      class MyView(APIView):
          permission_classes = [IsAuthenticated, RequiresFeatureFlag]
          feature_flag_key = "ai.orchestrator"

    Notes:
    - If a view does not define `feature_flag_key` or `feature_flag_keys`, this
      permission is a no-op and returns True.
    - Workspace resolution is best-effort; use view kwargs/query params or the
      user's active workspace when available.
    """

    message = "Feature not enabled."

    def has_permission(self, request, view):
        from components.shared_platform.application.providers.feature_flags_provider import (
            get_feature_flags_provider,
        )

        _flags = get_feature_flags_provider()

        flag_key = getattr(view, "feature_flag_key", None)
        flag_keys = getattr(view, "feature_flag_keys", None)
        required = []
        if flag_key:
            required.append(flag_key)
        if flag_keys:
            required.extend([key for key in flag_keys if key])
        if not required:
            return True

        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            user = None

        workspace_id = _flags.resolve_workspace_id_from_request(request, view=view)
        return all(
            _flags.is_feature_enabled(key, user=user, workspace_id=workspace_id, request=request)
            for key in required
        )


# =============================================================================
# WORKSPACE MEMBERSHIP PERMISSIONS
# =============================================================================

def _resolve_workspace_id(view, request):
    """Pull the workspace_id from common URL kwarg / query param names."""
    kwargs = getattr(view, "kwargs", {}) or {}
    for key in ("workspace_id", "workspace", "seed_id", "seed", "pk"):
        value = kwargs.get(key)
        if value:
            return value
    for key in ("workspace_id", "workspace", "seed_id", "seed"):
        value = request.query_params.get(key)
        if value:
            return value
    return None


class HasWorkspaceMembership(permissions.BasePermission):
    """Allow access only to authenticated users with an active membership in
    the workspace identified by the URL/query.

    Workspace owners always pass even if (legacy) they don't have an explicit
    WorkspaceMembership row — they're owners via Workspace.workspace_owner.
    Staff/superusers also bypass for support workflows.

    Use this for any workspace-scoped controller where the actor must be
    "in" the workspace to read or write. For finer-grained checks (e.g.
    "must be admin or owner"), compose with HasWorkspaceRole below.
    """

    message = "You must be a member of this workspace."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        workspace_id = _resolve_workspace_id(view, request)
        if not workspace_id:
            # No workspace in scope — let the view decide. This permission
            # only gates *workspace-scoped* endpoints; non-scoped endpoints
            # should pair this with another permission class.
            return True

        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider
        _wsp = get_workspaces_models_provider()
        Workspace = _wsp.Workspace
        WorkspaceMembership = _wsp.WorkspaceMembership

        if Workspace.objects.filter(
            id=workspace_id, workspace_owner_id=user.id
        ).exists():
            return True

        return WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user_id=user.id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists()


class HasWorkspaceRole(permissions.BasePermission):
    """Allow access only when the actor's WorkspaceMembership.role is in the
    set declared by the view.

    Usage::

        class ApproveDonationView(APIView):
            permission_classes = [HasWorkspaceRole]
            workspace_required_roles = ("owner", "admin")

    Owners of the workspace always pass for the implicit "owner" role even
    if they don't have an explicit membership row. Staff/superusers bypass.
    """

    message = "You don't have the required workspace role for this action."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        required = tuple(getattr(view, "workspace_required_roles", ()) or ())
        if not required:
            return True

        workspace_id = _resolve_workspace_id(view, request)
        if not workspace_id:
            return False

        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider
        _wsp = get_workspaces_models_provider()
        Workspace = _wsp.Workspace
        WorkspaceMembership = _wsp.WorkspaceMembership

        if "owner" in required and Workspace.objects.filter(
            id=workspace_id, workspace_owner_id=user.id
        ).exists():
            return True

        return WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user_id=user.id,
            status=WorkspaceMembership.Status.ACTIVE,
            role__in=required,
        ).exists()
