"""Workspace groups and permissions controller.

Endpoints for managing permission groups and permission grants within a workspace.
"""

import logging

from components.shared_kernel.application.providers.django_orm_provider import (
    get_django_orm_provider as _get_django_orm_provider,
)

logger = logging.getLogger(__name__)
_django_orm = _get_django_orm_provider()
IntegrityError = _django_orm.IntegrityError
from components.shared_kernel.application.providers.django_orm_provider import (
    get_django_orm_provider as _get_django_orm_provider,
)

_django_orm = _get_django_orm_provider()
Q = _django_orm.Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

_wsp = get_workspaces_models_provider()
Workspace = _wsp.Workspace
WorkspaceGroup = _wsp.WorkspaceGroup
WorkspaceGroupMembership = _wsp.WorkspaceGroupMembership
WorkspacePermissionGrant = _wsp.WorkspacePermissionGrant

# ---------------------------------------------------------------------------
# Permission keys registry
# ---------------------------------------------------------------------------

# Auto-Sec is a SOC/security product, so the permission catalog describes
# security operations — NOT the nonprofit surfaces this was forked from
# (donations/campaigns/grants/marketplace/writing). Retuned 2026-07-18.
# Owners bypass every check (``is_owner`` short-circuits); non-owners receive
# capabilities via role defaults or explicit direct grants (the member
# permission matrix edits the latter through ``/permissions/bulk``).
VALID_PERMISSION_KEYS = frozenset(
    {
        # Platform administration
        "manage_settings",
        "manage_billing",
        "manage_integrations",
        "manage_users",
        "manage_permissions",
        # SOC operations — findings/alerts triage
        "view_findings",
        "manage_findings",
        # Detections (rules / Sigma / detection engineering)
        "view_detections",
        "manage_detections",
        # Cases / incidents
        "view_cases",
        "manage_cases",
        # Response playbooks / automations
        "run_playbooks",
        "manage_playbooks",
        # AI agents (triage / specialist agents)
        "view_agents",
        "manage_agents",
        # Assets / inventory
        "view_assets",
        "manage_assets",
        # Audit trail + reporting
        "view_audit",
        "view_reports",
        "manage_reports",
        # Report/document authoring (the content context's Writing surface —
        # incident reports, RCAs, threat briefs — including AI-assist).
        # ``CanReadWriting``/``CanComposeWriting`` read these exact keys.
        "view_writing",
        "manage_writing",
    }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_workspace_or_404(workspace_id):
    """Fetch workspace using the base manager to include inactive ones."""
    return get_object_or_404(Workspace.objects.all_objects(), pk=workspace_id)


def _is_workspace_owner(workspace, user):
    """Return True if *user* is the workspace owner (root)."""
    return str(workspace.workspace_owner_id) == str(user.id)


def _user_has_permission(workspace, user, permission_key):
    """Check if *user* has a specific workspace permission (direct or via group)."""
    if _is_workspace_owner(workspace, user):
        return True

    # Direct user grant
    if WorkspacePermissionGrant.objects.filter(workspace=workspace, user=user, permission_key=permission_key).exists():
        return True

    # Grant via group membership
    user_group_ids = WorkspaceGroupMembership.objects.filter(user=user, group__workspace=workspace).values_list(
        "group_id", flat=True
    )

    return WorkspacePermissionGrant.objects.filter(
        workspace=workspace, group_id__in=user_group_ids, permission_key=permission_key
    ).exists()


def _is_workspace_admin(workspace, user):
    """Return True if *user* is an admin-tier member of the workspace.

    Both ``admin`` and ``owner`` membership roles are admin-tier (mirrors the
    backend role policy's ``_ADMIN_RBAC_ROLES``). A membership with
    ``role="owner"`` that is not the legacy ``workspace_owner_id`` would
    otherwise be wrongly denied management access.
    """
    from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

    WorkspaceMembership = get_workspaces_models_provider().WorkspaceMembership
    return WorkspaceMembership.objects.filter(
        workspace=workspace, user=user, role__in=("admin", "owner"), status="active"
    ).exists()


def _check_manage_permissions(workspace, user):
    """Return an error Response if the user cannot manage permissions, else None."""
    if (
        _is_workspace_owner(workspace, user)
        or _is_workspace_admin(workspace, user)
        or _user_has_permission(workspace, user, "manage_permissions")
    ):
        return None
    return Response(
        {"detail": "You do not have permission to manage groups and permissions in this workspace."},
        status=status.HTTP_403_FORBIDDEN,
    )


def _serialize_group(group, include_members=False):
    """Serialize a WorkspaceGroup to a dict."""
    data = {
        "id": str(group.id),
        "workspace_id": str(group.workspace_id),
        "name": group.name,
        "description": group.description,
        "created_by": str(group.created_by_id) if group.created_by_id else None,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "updated_at": group.updated_at.isoformat() if group.updated_at else None,
        "member_count": group.memberships.count(),
    }
    if include_members:
        data["members"] = [
            {
                "id": str(m.user_id),
                "username": m.user.username if hasattr(m.user, "username") else str(m.user_id),
                "added_by": str(m.added_by_id) if m.added_by_id else None,
                "added_at": m.added_at.isoformat() if m.added_at else None,
            }
            for m in group.memberships.select_related("user").all()
        ]
    return data


def _serialize_grant(grant):
    """Serialize a WorkspacePermissionGrant to a dict."""
    return {
        "id": str(grant.id),
        "workspace_id": str(grant.workspace_id),
        "permission_key": grant.permission_key,
        "user_id": str(grant.user_id) if grant.user_id else None,
        "group_id": str(grant.group_id) if grant.group_id else None,
        "granted_by": str(grant.granted_by_id) if grant.granted_by_id else None,
        "granted_at": grant.granted_at.isoformat() if grant.granted_at else None,
    }


# ============================================================================
# Group CRUD
# ============================================================================


class WorkspaceGroupListCreateView(APIView):
    """
    GET  /workspaces/{workspace_id}/groups/       -- list groups
    POST /workspaces/{workspace_id}/groups/       -- create group
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, workspace_id):
        workspace = _get_workspace_or_404(workspace_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        groups = WorkspaceGroup.objects.filter(workspace=workspace)
        return Response([_serialize_group(g) for g in groups], status=status.HTTP_200_OK)

    def post(self, request, workspace_id):
        workspace = _get_workspace_or_404(workspace_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "name is required."}, status=status.HTTP_400_BAD_REQUEST)

        description = request.data.get("description", "")

        try:
            group = WorkspaceGroup.objects.create(
                workspace=workspace,
                name=name,
                description=description,
                created_by=request.user,
            )
        except IntegrityError:
            return Response(
                {"detail": f"A group named '{name}' already exists in this workspace."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(_serialize_group(group), status=status.HTTP_201_CREATED)


class WorkspaceGroupDetailView(APIView):
    """
    GET    /workspaces/{workspace_id}/groups/{group_id}/  -- detail (with members)
    PATCH  /workspaces/{workspace_id}/groups/{group_id}/  -- update
    DELETE /workspaces/{workspace_id}/groups/{group_id}/  -- delete
    """

    permission_classes = (permissions.IsAuthenticated,)

    def _get_group(self, workspace_id, group_id):
        workspace = _get_workspace_or_404(workspace_id)
        group = get_object_or_404(WorkspaceGroup, pk=group_id, workspace=workspace)
        return workspace, group

    def get(self, request, workspace_id, group_id):
        workspace, group = self._get_group(workspace_id, group_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied
        return Response(_serialize_group(group, include_members=True), status=status.HTTP_200_OK)

    def patch(self, request, workspace_id, group_id):
        workspace, group = self._get_group(workspace_id, group_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        name = request.data.get("name")
        if name is not None:
            name = name.strip()
            if not name:
                return Response({"detail": "name cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
            group.name = name

        description = request.data.get("description")
        if description is not None:
            group.description = description

        try:
            group.save()
        except IntegrityError:
            return Response(
                {"detail": f"A group named '{name}' already exists in this workspace."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(_serialize_group(group, include_members=True), status=status.HTTP_200_OK)

    def delete(self, request, workspace_id, group_id):
        workspace, group = self._get_group(workspace_id, group_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# Group Members
# ============================================================================


class WorkspaceGroupMembersView(APIView):
    """
    POST /workspaces/{workspace_id}/groups/{group_id}/members/  -- add members
    """

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, workspace_id, group_id):
        workspace = _get_workspace_or_404(workspace_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        group = get_object_or_404(WorkspaceGroup, pk=group_id, workspace=workspace)
        user_ids = request.data.get("user_ids", [])
        if not user_ids or not isinstance(user_ids, list):
            return Response({"detail": "user_ids list is required."}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.auth import get_user_model

        User = get_user_model()
        added = []
        already_exists = []

        for uid in user_ids:
            try:
                user = User.objects.get(pk=uid)
            except User.DoesNotExist:
                continue
            try:
                WorkspaceGroupMembership.objects.create(group=group, user=user, added_by=request.user)
                added.append(str(uid))
            except IntegrityError:
                already_exists.append(str(uid))

        return Response(
            {"added": added, "already_members": already_exists},
            status=status.HTTP_200_OK,
        )


class WorkspaceGroupMemberRemoveView(APIView):
    """
    DELETE /workspaces/{workspace_id}/groups/{group_id}/members/{user_id}/  -- remove member
    """

    permission_classes = (permissions.IsAuthenticated,)

    def delete(self, request, workspace_id, group_id, user_id):
        workspace = _get_workspace_or_404(workspace_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        group = get_object_or_404(WorkspaceGroup, pk=group_id, workspace=workspace)
        membership = get_object_or_404(WorkspaceGroupMembership, group=group, user_id=user_id)
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# Permission Grants
# ============================================================================


class WorkspacePermissionListCreateView(APIView):
    """
    GET  /workspaces/{workspace_id}/permissions/       -- list grants
    POST /workspaces/{workspace_id}/permissions/       -- create grant
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, workspace_id):
        workspace = _get_workspace_or_404(workspace_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        grants = WorkspacePermissionGrant.objects.filter(workspace=workspace).order_by("permission_key")
        return Response([_serialize_grant(g) for g in grants], status=status.HTTP_200_OK)

    def post(self, request, workspace_id):
        workspace = _get_workspace_or_404(workspace_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        permission_key = request.data.get("permission_key", "").strip()
        if permission_key not in VALID_PERMISSION_KEYS:
            return Response(
                {"detail": f"Invalid permission_key. Valid keys: {sorted(VALID_PERMISSION_KEYS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_id = request.data.get("user_id")
        group_id = request.data.get("group_id")

        if not user_id and not group_id:
            return Response(
                {"detail": "Either user_id or group_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user_id and group_id:
            return Response(
                {"detail": "Provide either user_id or group_id, not both."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        kwargs = {
            "workspace": workspace,
            "permission_key": permission_key,
            "granted_by": request.user,
        }

        if user_id:
            # Prevent granting permissions to the workspace owner (they already have all)
            if _is_workspace_owner(workspace, type("U", (), {"id": user_id})()):
                return Response(
                    {"detail": "The workspace owner already has all permissions."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user = get_object_or_404(User, pk=user_id)
            kwargs["user"] = user
            # Check for duplicate
            if WorkspacePermissionGrant.objects.filter(
                workspace=workspace, permission_key=permission_key, user=user
            ).exists():
                return Response(
                    {"detail": "This permission is already granted to this user."},
                    status=status.HTTP_409_CONFLICT,
                )
        else:
            group = get_object_or_404(WorkspaceGroup, pk=group_id, workspace=workspace)
            kwargs["group"] = group
            if WorkspacePermissionGrant.objects.filter(
                workspace=workspace, permission_key=permission_key, group=group
            ).exists():
                return Response(
                    {"detail": "This permission is already granted to this group."},
                    status=status.HTTP_409_CONFLICT,
                )

        grant = WorkspacePermissionGrant.objects.create(**kwargs)
        return Response(_serialize_grant(grant), status=status.HTTP_201_CREATED)


class WorkspacePermissionRevokeView(APIView):
    """
    DELETE /workspaces/{workspace_id}/permissions/{grant_id}/  -- revoke grant
    """

    permission_classes = (permissions.IsAuthenticated,)

    def delete(self, request, workspace_id, grant_id):
        workspace = _get_workspace_or_404(workspace_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        grant = get_object_or_404(WorkspacePermissionGrant, pk=grant_id, workspace=workspace)
        grant.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspacePermissionBulkView(APIView):
    """
    POST /workspaces/{workspace_id}/permissions/bulk/  -- bulk grant/revoke

    Body:
    {
        "action": "grant" | "revoke",
        "permission_keys": ["manage_budgets", "view_reports"],
        "user_ids": ["uuid1", "uuid2"]  // or "group_ids": ["uuid1"]
    }
    """

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, workspace_id):
        workspace = _get_workspace_or_404(workspace_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        action = request.data.get("action")
        if action not in ("grant", "revoke"):
            return Response(
                {"detail": "action must be 'grant' or 'revoke'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        permission_keys = request.data.get("permission_keys", [])
        if not permission_keys or not isinstance(permission_keys, list):
            return Response(
                {"detail": "permission_keys list is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invalid_keys = set(permission_keys) - VALID_PERMISSION_KEYS
        if invalid_keys:
            return Response(
                {"detail": f"Invalid permission keys: {sorted(invalid_keys)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_ids = request.data.get("user_ids", [])
        group_ids = request.data.get("group_ids", [])

        if not user_ids and not group_ids:
            return Response(
                {"detail": "Provide user_ids or group_ids."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_count = 0
        revoked_count = 0

        if action == "grant":
            if user_ids:
                from django.contrib.auth import get_user_model

                User = get_user_model()
                for uid in user_ids:
                    try:
                        user = User.objects.get(pk=uid)
                    except User.DoesNotExist:
                        continue
                    if _is_workspace_owner(workspace, user):
                        continue
                    for key in permission_keys:
                        _, created = WorkspacePermissionGrant.objects.get_or_create(
                            workspace=workspace,
                            permission_key=key,
                            user=user,
                            defaults={"granted_by": request.user},
                        )
                        if created:
                            created_count += 1

            if group_ids:
                for gid in group_ids:
                    try:
                        group = WorkspaceGroup.objects.get(pk=gid, workspace=workspace)
                    except WorkspaceGroup.DoesNotExist:
                        continue
                    for key in permission_keys:
                        _, created = WorkspacePermissionGrant.objects.get_or_create(
                            workspace=workspace,
                            permission_key=key,
                            group=group,
                            defaults={"granted_by": request.user},
                        )
                        if created:
                            created_count += 1

            return Response({"granted": created_count}, status=status.HTTP_200_OK)

        else:  # revoke
            q = Q(workspace=workspace, permission_key__in=permission_keys)
            if user_ids:
                q &= Q(user_id__in=user_ids)
            if group_ids:
                q &= Q(group_id__in=group_ids)

            revoked_count = WorkspacePermissionGrant.objects.filter(q).delete()[0]
            return Response({"revoked": revoked_count}, status=status.HTTP_200_OK)


class WorkspaceMyPermissionsView(APIView):
    """GET /workspaces/{workspace_id}/permissions/my/  — current user's effective permissions.

    Unions three grant sources so the frontend gates match the backend
    ``has_workspace_permission`` gate exactly:

    1. **Role permissions** — read off the user's ``WorkspaceMembership``
       via ``membership_has_permission``. This covers the seeded system
       roles (owner, admin, finance, donation_steward, etc.) and any
       workspace-custom role bound to the membership. Phase 2 onward is
       the authoritative source.
    2. **Direct grants** — ``WorkspacePermissionGrant`` rows attached
       directly to the user.
    3. **Group grants** — ``WorkspacePermissionGrant`` rows attached to
       ``WorkspaceGroup`` rows the user belongs to.

    Workspace owner short-circuits to every valid key (structural, not
    role-based). Team-only users (no ``WorkspaceMembership`` row but on
    a workspace team) fall through the same team-membership
    compatibility path ``HasWorkspacePermission`` uses, so they see the
    seeded ``member`` bundle here too. Both fallbacks disappear in
    Phase 3b once the backfill has run in production.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, workspace_id):
        workspace = _get_workspace_or_404(workspace_id)
        user = request.user

        if _is_workspace_owner(workspace, user):
            return Response(
                {
                    "is_owner": True,
                    "permissions": sorted(VALID_PERMISSION_KEYS),
                },
                status=status.HTTP_200_OK,
            )

        role_keys = self._role_permissions(workspace, user)
        direct_keys = set(
            WorkspacePermissionGrant.objects.filter(workspace=workspace, user=user).values_list(
                "permission_key", flat=True
            )
        )
        user_group_ids = WorkspaceGroupMembership.objects.filter(user=user, group__workspace=workspace).values_list(
            "group_id", flat=True
        )
        group_keys = set(
            WorkspacePermissionGrant.objects.filter(workspace=workspace, group_id__in=user_group_ids).values_list(
                "permission_key", flat=True
            )
        )

        effective = role_keys | direct_keys | group_keys

        return Response(
            {
                "is_owner": False,
                "permissions": sorted(effective),
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _role_permissions(workspace, user) -> set[str]:
        """Return the permission keys the user carries via their workspace role.

        Mirrors ``HasWorkspacePermission`` resolution so the list
        returned here equals the set of keys the backend gate will
        actually allow.
        """
        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

        WorkspaceMembership = get_workspaces_models_provider().WorkspaceMembership

        membership = (
            WorkspaceMembership.objects.filter(
                workspace=workspace,
                user=user,
                status=WorkspaceMembership.Status.ACTIVE,
            )
            .select_related("workspace_role")
            .first()
        )
        if membership is not None:
            if membership.workspace_role is not None:
                return set(membership.workspace_role.permissions or [])
            legacy_role = getattr(membership, "role", None) or ""
            if legacy_role:
                from components.workspace.application.providers.workspaces_models_provider import (
                    get_workspaces_models_provider,
                )

                WorkspaceRole = get_workspaces_models_provider().WorkspaceRole
                system_role = (
                    WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug=legacy_role)
                    .only("permissions")
                    .first()
                )
                if system_role is not None:
                    return set(system_role.permissions or [])
            return set()

        # Team-only compatibility — same path HasWorkspacePermission uses.
        from components.team.application.providers.team_models_provider import get_team_models_provider

        Team = get_team_models_provider().Team
        if Team.objects.filter(
            workspace=workspace,
            status=Team.ACTIVE,
            members__id=user.id,
        ).exists():
            from components.workspace.application.providers.workspaces_models_provider import (
                get_workspaces_models_provider,
            )

            WorkspaceRole = get_workspaces_models_provider().WorkspaceRole
            member_role = (
                WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug="member")
                .only("permissions")
                .first()
            )
            if member_role is not None:
                return set(member_role.permissions or [])

        return set()


# ============================================================================
# Workspace members — role assignment + effective-permission admin views
# ============================================================================


def _serialize_member_effective_permissions(
    *, membership, workspace, direct_grant_keys: set[str], group_grant_keys: set[str]
) -> dict:
    """Return a row for the admin matrix describing a single member's access.

    ``role_permissions`` are the keys the user carries *because of their
    role* (system or workspace-custom). ``direct_permissions`` are the
    keys granted explicitly on top — editable in the matrix. The union
    of both (plus owner short-circuit) equals what the backend gate
    will actually allow. Surfacing them separately is what lets the UI
    draw role-derived cells as locked "via role" and reserve the
    toggle for the override layer.
    """
    user = getattr(membership, "user", None)
    user_id = getattr(user, "id", None) or getattr(membership, "user_id", None)

    role_permissions: list[str] = []
    role_slug: str | None = None
    role_name: str | None = None
    workspace_role = getattr(membership, "workspace_role", None)
    if workspace_role is not None:
        role_slug = workspace_role.slug
        role_name = workspace_role.name
        role_permissions = sorted(workspace_role.permissions or [])
    else:
        legacy_role = getattr(membership, "role", None) or ""
        if legacy_role:
            from components.workspace.application.providers.workspaces_models_provider import (
                get_workspaces_models_provider,
            )

            WorkspaceRole = get_workspaces_models_provider().WorkspaceRole
            fallback = (
                WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug=legacy_role)
                .only("slug", "name", "permissions")
                .first()
            )
            if fallback is not None:
                role_slug = fallback.slug
                role_name = fallback.name
                role_permissions = sorted(fallback.permissions or [])

    return {
        "user_id": str(user_id) if user_id else None,
        "email": getattr(user, "email", "") or "",
        "name": (f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}").strip()
        or getattr(user, "username", "")
        or "",
        "role_slug": role_slug,
        "role_name": role_name,
        "role_permissions": role_permissions,
        "direct_permissions": sorted(direct_grant_keys),
        "group_permissions": sorted(group_grant_keys),
        "is_owner": str(workspace.workspace_owner_id) == str(user_id),
        "membership_status": getattr(membership, "status", ""),
    }


class WorkspaceMembersEffectivePermissionsView(APIView):
    """GET /workspaces/<ws>/members/effective-permissions/  — admin matrix source.

    Returns one row per active ``WorkspaceMembership`` with four
    separate permission sets: role-derived (from
    ``workspace_role`` FK or the legacy-role fallback), direct-user
    grants, group-mediated grants, and an ``is_owner`` flag. The UI
    unions these; separating them lets the matrix render role-derived
    cells as locked "via role" and expose toggles only for the
    override layer.

    Authorization: caller must be able to manage permissions in the
    workspace (same gate the permission-list / grant endpoints use —
    owner, admin, or anyone carrying ``manage_permissions``).
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, workspace_id):
        workspace = _get_workspace_or_404(workspace_id)
        denied = _check_manage_permissions(workspace, request.user)
        if denied:
            return denied

        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

        WorkspaceMembership = get_workspaces_models_provider().WorkspaceMembership

        memberships = (
            WorkspaceMembership.objects.filter(workspace=workspace, status=WorkspaceMembership.Status.ACTIVE)
            .select_related("user", "workspace_role")
            .order_by("user__email")
        )

        user_ids = [m.user_id for m in memberships]
        direct_grants_by_user: dict[str, set[str]] = {}
        for grant in WorkspacePermissionGrant.objects.filter(workspace=workspace, user_id__in=user_ids).values_list(
            "user_id", "permission_key"
        ):
            direct_grants_by_user.setdefault(str(grant[0]), set()).add(grant[1])

        group_ids_by_user: dict[str, set] = {}
        for row in WorkspaceGroupMembership.objects.filter(
            user_id__in=user_ids, group__workspace=workspace
        ).values_list("user_id", "group_id"):
            group_ids_by_user.setdefault(str(row[0]), set()).add(row[1])

        all_group_ids = {gid for ids in group_ids_by_user.values() for gid in ids}
        grants_by_group: dict[str, set[str]] = {}
        if all_group_ids:
            for row in WorkspacePermissionGrant.objects.filter(
                workspace=workspace, group_id__in=list(all_group_ids)
            ).values_list("group_id", "permission_key"):
                grants_by_group.setdefault(str(row[0]), set()).add(row[1])

        rows = []
        seen_user_ids: set[str] = set()
        for membership in memberships:
            user_id_str = str(membership.user_id)
            direct_keys = direct_grants_by_user.get(user_id_str, set())
            group_keys: set[str] = set()
            for gid in group_ids_by_user.get(user_id_str, set()):
                group_keys |= grants_by_group.get(str(gid), set())
            rows.append(
                _serialize_member_effective_permissions(
                    membership=membership,
                    workspace=workspace,
                    direct_grant_keys=direct_keys,
                    group_grant_keys=group_keys,
                )
            )
            seen_user_ids.add(user_id_str)

        # Surface the workspace owner even if they don't have an explicit
        # WorkspaceMembership row (some legacy workspaces were created
        # before the bootstrap path that auto-creates the owner row ran).
        # Admins expect to see the owner in the matrix.
        owner_id_str = str(workspace.workspace_owner_id) if workspace.workspace_owner_id else ""
        if owner_id_str and owner_id_str not in seen_user_ids:
            rows.insert(0, self._owner_row_without_membership(workspace))

        return Response({"members": rows}, status=status.HTTP_200_OK)

    @staticmethod
    def _owner_row_without_membership(workspace) -> dict:
        """Synthesize a member row for an owner with no WorkspaceMembership.

        Ownership is structural — the gate short-circuits on it — so
        the matrix shows them as ``is_owner=True`` with the full key
        set available but no distinct role/grants to edit here.
        """
        owner_user = getattr(workspace, "workspace_owner", None)
        return {
            "user_id": str(workspace.workspace_owner_id) if workspace.workspace_owner_id else None,
            "email": getattr(owner_user, "email", "") or "",
            "name": (
                f"{getattr(owner_user, 'first_name', '') or ''} {getattr(owner_user, 'last_name', '') or ''}"
            ).strip()
            or getattr(owner_user, "username", "")
            or "",
            "role_slug": None,
            "role_name": None,
            "role_permissions": sorted(VALID_PERMISSION_KEYS),
            "direct_permissions": [],
            "group_permissions": [],
            "is_owner": True,
            "membership_status": "",
        }


class WorkspaceMemberRoleView(APIView):
    """PATCH /workspaces/<ws>/members/<user_id>/role/  — set a member's role.

    Request body: ``{"role_slug": "<slug>"}`` — the seeded system slug
    or a workspace-custom-role slug. The old ``role`` string is also
    updated to match (kept in lockstep until Phase 3 drops the string
    column).

    Authorization: ``manage_users`` — admins manage who is what in the
    workspace. Persona is NEVER consulted.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def patch(self, request, workspace_id, user_id):
        workspace = _get_workspace_or_404(workspace_id)

        # Gate on the capability so any role carrying ``manage_users``
        # (not just owner/admin) can reassign roles. Owner short-circuits
        # the same way ``has_workspace_permission`` does.
        if not _is_workspace_owner(workspace, request.user):
            if not _user_has_permission(workspace, request.user, "manage_users"):
                from components.membership.application.services.membership_permission_service import (
                    membership_has_permission,
                )
                from components.workspace.application.providers.workspaces_models_provider import (
                    get_workspaces_models_provider,
                )

                _WM = get_workspaces_models_provider().WorkspaceMembership
                actor_membership = (
                    _WM.objects.filter(workspace=workspace, user=request.user, status=_WM.Status.ACTIVE)
                    .select_related("workspace_role")
                    .first()
                )
                if not membership_has_permission(actor_membership, "manage_users"):
                    return Response(
                        {"detail": "You do not have permission to change member roles."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        role_slug = (request.data.get("role_slug") or "").strip()
        if not role_slug:
            return Response(
                {"detail": "role_slug is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

        _wsp_models = get_workspaces_models_provider()
        WorkspaceMembership = _wsp_models.WorkspaceMembership
        WorkspaceRole = _wsp_models.WorkspaceRole

        # Workspace-custom role first (scoped to this workspace), then system role.
        target_role = (
            WorkspaceRole.objects.filter(workspace=workspace, slug=role_slug, is_system=False).first()
            or WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug=role_slug).first()
        )
        if target_role is None:
            return Response(
                {"detail": f"Unknown role slug: {role_slug!r}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership = (
            WorkspaceMembership.objects.filter(workspace=workspace, user_id=user_id)
            .select_related("user", "workspace_role")
            .first()
        )
        if membership is None:
            return Response(
                {"detail": "That user is not a member of this workspace."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Block demoting the workspace owner to something else — ownership is
        # structural and must be transferred via the ownership endpoint, not
        # the role picker.
        if str(workspace.workspace_owner_id) == str(membership.user_id):
            return Response(
                {"detail": "The workspace owner's role cannot be changed here."},
                status=status.HTTP_409_CONFLICT,
            )

        membership.workspace_role = target_role
        # Keep legacy string aligned for the small number of gates still
        # reading it. System-role slugs that don't match the legacy
        # TextChoices just keep their previous value.
        if target_role.is_system and target_role.slug in (
            WorkspaceMembership.Role.OWNER,
            WorkspaceMembership.Role.ADMIN,
            WorkspaceMembership.Role.MEMBER,
            WorkspaceMembership.Role.VIEWER,
        ):
            membership.role = target_role.slug
            membership.save(update_fields=["workspace_role", "role"])
        else:
            membership.save(update_fields=["workspace_role"])

        # Fire the ``contact_updated`` workflow trigger — a directory contact's
        # role just changed. The contact target is the member (user), so the
        # dispatcher can start a run / resolve their membership. Routed through
        # the workflow provider (controllers must not import the concrete
        # dispatcher — test_controllers_do_not_import_concrete_adapters).
        try:
            from components.workflow.application.providers.workflow_dispatcher_provider import (
                get_workflow_dispatcher_provider,
            )

            get_workflow_dispatcher_provider().emit_workflow_event(
                workspace_id=str(workspace.id),
                source_type="directory",
                trigger_type="contact_updated",
                payload={
                    "workspace_id": str(workspace.id),
                    "target_type": "contact",
                    "target_id": str(membership.user_id),
                    "contact_id": str(membership.user_id),
                    "user_id": str(request.user.id),
                    "changed_field": "role",
                    "role_slug": target_role.slug,
                },
                source_id=str(workspace.id),
                idempotency_key=(f"contact_updated:{workspace.id}:{membership.user_id}:{target_role.slug}"),
            )
        except Exception:
            logger.exception(
                "Failed to emit contact_updated workflow event workspace_id=%s user_id=%s",
                workspace.id,
                membership.user_id,
            )

        return Response(
            {
                "user_id": str(membership.user_id),
                "role_slug": target_role.slug,
                "role_name": target_role.name,
                "role_permissions": sorted(target_role.permissions or []),
            },
            status=status.HTTP_200_OK,
        )
