"""Workspace-scoped DRF permission classes.

These permissions resolve workspace/team membership to authorize access
to workspace-scoped resources. They were extracted from apps/users/permissions.py
because they are a workspace concern, not an identity concern.

All workspace/team membership resolution logic lives here.
"""

import json

from django.apps import apps
from rest_framework import permissions
from rest_framework.exceptions import UnsupportedMediaType


def _get_team_models():
    from components.team.application.providers.team_models_provider import get_team_models_provider
    Team = get_team_models_provider().Team
    TeamMembership = get_team_models_provider().TeamMembership
    return Team, TeamMembership


def _get_workspace_models():
    from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider
    _wsp = get_workspaces_models_provider()
    return _wsp.Workspace, _wsp.WorkspaceMembership


def _safe_json_body(request):
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


def _safe_request_data(request):
    try:
        return getattr(request, "data", {}) or {}
    except UnsupportedMediaType:
        return _safe_json_body(request)


class IsOrgOwnerOrMember(permissions.BasePermission):
    """Allow access to organization owners and members of its teams."""

    message = "You must belong to the organization to perform this action."
    # "seed"/"seed_id" are the frontend's legacy vocabulary for workspace —
    # older clients still send them (e.g. the pre-2026-07 Teams index).
    workspace_lookup_keys = ("workspace_id", "workspace", "workspaceId", "workspace_pk", "seed", "seed_id")
    team_lookup_keys = ("team_id", "team", "teamId", "team_pk")
    project_lookup_keys = ("project_id", "project", "projectId", "project_pk")
    task_lookup_keys = ("task_id", "task", "taskId", "task_pk")
    column_lookup_keys = ("column_id", "column", "columnId", "column_pk")

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        workspace = self._resolve_workspace(request, view)
        if workspace is None:
            if self._has_object_lookup(request, view):
                return True
            self.message = "Organization identifier is required for this action."
            return False

        return self._is_member(user, workspace)

    def has_object_permission(self, request, view, obj):
        Workspace, WorkspaceMembership = _get_workspace_models()
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        workspace = None
        if isinstance(obj, Workspace):
            workspace = obj
        elif hasattr(obj, "workspace"):
            workspace = getattr(obj, "workspace", None)
        elif hasattr(obj, "workspace_id"):
            workspace = Workspace.objects.filter(id=getattr(obj, "workspace_id", None)).first()

        if workspace is None:
            workspace = self._resolve_workspace(request, view)

        if workspace is None:
            self.message = "Organization identifier is required for this action."
            return False

        return self._is_member(user, workspace)

    def _is_member(self, user, workspace):
        Team, TeamMembership = _get_team_models()
        Workspace, WorkspaceMembership = _get_workspace_models()
        if str(workspace.workspace_owner_id) == str(user.id):
            return True

        if WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=user,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists():
            return True

        return Team.objects.filter(
            workspace=workspace,
            status=Team.ACTIVE,
            members__id=user.id,
        ).exists()

    def _has_object_lookup(self, request, view):
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

    def _resolve_workspace(self, request, view):
        Workspace, WorkspaceMembership = _get_workspace_models()
        workspace_identifier = self._extract_workspace_identifier(request, view)
        workspace = None
        if workspace_identifier:
            try:
                workspace = Workspace.objects.filter(id=workspace_identifier).first()
            except (ValueError, TypeError):
                workspace = None

        if workspace:
            return workspace

        return self._workspace_from_related_identifiers(request, view)

    def _extract_workspace_identifier(self, request, view):
        parser_context = getattr(request, "parser_context", None) or {}
        kwargs = parser_context.get("kwargs", {})
        for key in self.workspace_lookup_keys:
            value = kwargs.get(key)
            if value:
                return value

        view_kwargs = getattr(view, "kwargs", {}) if hasattr(view, "kwargs") else {}
        for key in self.workspace_lookup_keys:
            value = view_kwargs.get(key)
            if value:
                return value

        data = self._get_request_data(request)
        for key in self.workspace_lookup_keys:
            value = data.get(key)
            if value:
                return value

        query_params = getattr(request, "query_params", None)
        if query_params:
            for key in self.workspace_lookup_keys:
                value = query_params.get(key)
                if value:
                    return value

        return None

    def _workspace_from_related_identifiers(self, request, view):
        Team, TeamMembership = _get_team_models()
        Workspace, WorkspaceMembership = _get_workspace_models()
        team_id = self._lookup_from_sources(self.team_lookup_keys, request, view)
        if team_id:
            try:
                team = Team.objects.select_related('workspace').get(id=team_id)
                return team.workspace
            except (Team.DoesNotExist, ValueError, TypeError):
                pass

        project = self._fetch_related_instance('project', 'Project', self.project_lookup_keys, request, view)
        if project and getattr(project, 'workspace_id', None):
            return project.workspace

        task = self._fetch_related_instance('project', 'Task', self.task_lookup_keys, request, view)
        if task and getattr(task, 'workspace_id', None):
            return task.workspace

        column = self._fetch_related_instance('project', 'Column', self.column_lookup_keys, request, view)
        if column and getattr(column, 'workspace_id', None):
            return column.workspace

        profile = getattr(request.user, 'profile', None)
        if profile and profile.active_team_id:
            team = Team.objects.filter(
                id=profile.active_team_id,
                members__id=getattr(request.user, 'id', None),
            ).select_related('workspace').first()
            if team:
                return team.workspace

        if profile and profile.active_workspace_id:
            try:
                return Workspace.objects.filter(id=profile.active_workspace_id).first()
            except (ValueError, TypeError):
                return None

        return None

    def _fetch_related_instance(self, app_label, model_name, lookup_keys, request, view):
        identifier = self._lookup_from_sources(lookup_keys, request, view)
        if not identifier:
            return None
        model = self._get_model(app_label, model_name)
        if not model:
            return None
        try:
            return model.objects.filter(id=identifier).first()
        except (ValueError, TypeError):
            return None

    def _get_model(self, app_label, model_name):
        try:
            return apps.get_model(app_label, model_name)
        except (LookupError, ValueError):
            return None

    def _lookup_from_sources(self, keys, request, view):
        for source in self._sources(request, view):
            for key in keys:
                value = source.get(key)
                if value:
                    return value
        return None

    def _get_request_data(self, request):
        return _safe_request_data(request)

    def _parse_json_body(self, request):
        return _safe_json_body(request)

    def _sources(self, request, view):
        sources = []
        data = self._get_request_data(request)
        if data:
            sources.append(data)
        query_params = getattr(request, "query_params", None)
        if query_params:
            sources.append(query_params)
        parser_context = getattr(request, "parser_context", None) or {}
        kwargs = parser_context.get("kwargs")
        if kwargs:
            sources.append(kwargs)
        view_kwargs = getattr(view, "kwargs", None)
        if view_kwargs:
            sources.append(view_kwargs)
        return [source for source in sources if source]


class IsWorkspaceAdmin(IsOrgOwnerOrMember):
    """Allow workspace owners/admins to manage organization-level resources."""

    message = "You must be an organization admin to perform this action."

    def _is_member(self, user, workspace):
        Workspace, WorkspaceMembership = _get_workspace_models()
        if str(workspace.workspace_owner_id) == str(user.id):
            return True

        return WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=user,
            status=WorkspaceMembership.Status.ACTIVE,
            role__in=[WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN],
        ).exists()


class IsTeamLead(permissions.BasePermission):
    """Allow team leads (or workspace admins) to manage team-scoped settings."""

    message = "You must be a team lead to perform this action."
    team_lookup_keys = ("team_id", "team", "teamId", "team_pk")

    def has_permission(self, request, view):
        Team, TeamMembership = _get_team_models()
        Workspace, WorkspaceMembership = _get_workspace_models()
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        team = self._resolve_team(request, view)
        if team is None:
            return False

        if str(team.workspace.workspace_owner_id) == str(user.id):
            return True

        if WorkspaceMembership.objects.filter(
            workspace=team.workspace,
            user=user,
            status=WorkspaceMembership.Status.ACTIVE,
            role__in=[WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN],
        ).exists():
            return True

        return TeamMembership.objects.filter(
            team=team,
            user=user,
            status=TeamMembership.Status.ACTIVE,
            role=TeamMembership.Role.LEAD,
        ).exists()

    def _resolve_team(self, request, view):
        identifier = None
        data = _safe_request_data(request)
        for key in self.team_lookup_keys:
            if data.get(key):
                identifier = data.get(key)
                break
        if not identifier:
            query_params = getattr(request, "query_params", None) or {}
            for key in self.team_lookup_keys:
                if query_params.get(key):
                    identifier = query_params.get(key)
                    break
        if not identifier:
            parser_context = getattr(request, "parser_context", None) or {}
            kwargs = parser_context.get("kwargs", {}) or {}
            for key in self.team_lookup_keys:
                if kwargs.get(key):
                    identifier = kwargs.get(key)
                    break
        if not identifier and hasattr(view, "kwargs"):
            for key in self.team_lookup_keys:
                if view.kwargs.get(key):
                    identifier = view.kwargs.get(key)
                    break
        if not identifier:
            return None
        Team, TeamMembership = _get_team_models()
        try:
            return Team.objects.select_related("workspace").filter(id=identifier).first()
        except (ValueError, TypeError):
            return None


class IsTeamEditor(IsTeamLead):
    """Allow team editors (or leads/admins) to manage team content."""

    message = "You must be a team editor to perform this action."

    def has_permission(self, request, view):
        Team, TeamMembership = _get_team_models()
        Workspace, WorkspaceMembership = _get_workspace_models()
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        team = self._resolve_team(request, view)
        if team is None:
            return False

        if str(team.workspace.workspace_owner_id) == str(user.id):
            return True

        if WorkspaceMembership.objects.filter(
            workspace=team.workspace,
            user=user,
            status=WorkspaceMembership.Status.ACTIVE,
            role__in=[WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN],
        ).exists():
            return True

        return TeamMembership.objects.filter(
            team=team,
            user=user,
            status=TeamMembership.Status.ACTIVE,
            role__in=[TeamMembership.Role.LEAD, TeamMembership.Role.EDITOR],
        ).exists()


class IsWorkspaceFollowerOrMember(IsOrgOwnerOrMember):
    """Allow workspace owners, team members, or followers (plus staff) to interact with a workspace."""

    message = "You need to follow or belong to this organization to perform this action."

    def has_permission(self, request, view):
        Team, TeamMembership = _get_team_models()
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        workspace = self._resolve_workspace(request, view)
        if workspace is None:
            self.message = "Organization identifier is required for this action."
            return False

        if str(workspace.workspace_owner_id) == str(user.id):
            return True

        if workspace.followers.filter(id=user.id).exists():
            return True

        return Team.objects.filter(
            workspace=workspace,
            status=Team.ACTIVE,
            members__id=user.id,
        ).exists()


# The capability-backed gate moved to ``components.membership.api.permissions``
# in the role-redesign refactor — permissions are membership-scoped per
# ADR 0002. Re-export for back-compat so existing
# ``from components.workspace.api.permissions import has_workspace_permission``
# callers keep working while they migrate to the new import path.
from components.membership.api.permissions import (  # noqa: E402,F401
    has_workspace_permission,
)
