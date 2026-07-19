"""ORM repository adapters for cross-context tool data access.

Each class implements a port from ``components.agents.ports.tool_data_port``
using lazy Django ORM imports to avoid circular-import and app-readiness issues.

These adapters are injected into LangChain tool classes via ``AIProvider``
so that tools never import Django models directly.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.tool_data_port import (
    PermissionToolRepository,
    ProjectToolRepository,
    TaskToolRepository,
    UserToolRepository,
    WorkspaceToolRepository,
)

# ──────────────────────────────────────────────────────────────────────
# Project / Task
# ──────────────────────────────────────────────────────────────────────


class OrmProjectToolRepository(ProjectToolRepository):
    def list_for_workspace(
        self,
        workspace_id: str,
        *,
        team_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from infrastructure.persistence.project.models import Project

        qs = Project.objects.filter(workspace_id=workspace_id)
        if team_id:
            qs = qs.filter(team_id=team_id)
        return list(qs.values())

    def get_by_id(self, project_id: str) -> dict[str, Any] | None:
        from infrastructure.persistence.project.models import Project

        return Project.objects.filter(id=project_id).values().first()

    def create(self, *, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
        from infrastructure.persistence.project.models import Project

        obj = Project.objects.create(workspace_id=workspace_id, **data)
        return {"id": str(obj.id), **data}


class OrmTaskToolRepository(TaskToolRepository):
    def list_for_workspace(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        assignee_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        from infrastructure.persistence.project.models import Task

        qs = Task.objects.filter(workspace_id=workspace_id)
        if project_id:
            qs = qs.filter(project_id=project_id)
        if assignee_id:
            qs = qs.filter(assigned_to__id=assignee_id)
        if status:
            qs = qs.filter(status=status)
        return list(qs.values())

    def get_by_id(self, task_id: str) -> dict[str, Any] | None:
        from infrastructure.persistence.project.models import Task

        return Task.objects.filter(id=task_id).values().first()

    def create(self, *, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
        from infrastructure.persistence.project.models import Task

        obj = Task.objects.create(workspace_id=workspace_id, **data)
        return {"id": str(obj.id), **data}

    def update(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]:
        from infrastructure.persistence.project.models import Task

        Task.objects.filter(id=task_id).update(**data)
        return {"id": task_id, **data}

    def add_comment(self, *, task_id: str, author_id: str, content: str) -> dict[str, Any]:
        from infrastructure.persistence.project.models import TaskComment

        obj = TaskComment.objects.create(
            task_id=task_id,
            author_id=author_id,
            comment=content,
        )
        return {"id": str(obj.id), "task_id": task_id, "content": content}

    def list_columns(self, project_id: str) -> list[dict[str, Any]]:
        from infrastructure.persistence.project.models import Column

        return list(
            Column.objects.filter(project_id=project_id).values(
                "id",
                "title",
                "order",
            )
        )


# ──────────────────────────────────────────────────────────────────────
# Workspace
# ──────────────────────────────────────────────────────────────────────


class OrmWorkspaceToolRepository(WorkspaceToolRepository):
    def get_by_id(self, workspace_id: str) -> dict[str, Any] | None:
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(id=workspace_id).values().first()

    def get_members(self, workspace_id: str) -> list[dict[str, Any]]:
        from infrastructure.persistence.workspaces.models import Workspace

        ws = Workspace.objects.filter(id=workspace_id).first()
        if not ws:
            return []
        return list(ws.members.all().values("id", "username", "email", "first_name", "last_name"))

    def get_teams(self, workspace_id: str) -> list[dict[str, Any]]:
        from infrastructure.persistence.workspaces.models import Workspace

        ws = Workspace.objects.filter(id=workspace_id).first()
        if not ws:
            return []
        return list(ws.teams.all().values("id", "name"))

    def get_categories(self, workspace_id: str) -> list[dict[str, Any]]:
        from infrastructure.persistence.workspaces.models import WorkspaceCategory

        return list(WorkspaceCategory.objects.filter(workspace_id=workspace_id).values())

    def get_tags(self, workspace_id: str) -> list[dict[str, Any]]:
        from infrastructure.persistence.workspaces.models import Workspace

        ws = Workspace.objects.filter(id=workspace_id).first()
        if not ws:
            return []
        return list(ws.tags.all().values("id", "name"))


# ──────────────────────────────────────────────────────────────────────
# User / Permission
# ──────────────────────────────────────────────────────────────────────


class OrmUserToolRepository(UserToolRepository):
    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return (
            User.objects.filter(id=user_id)
            .values(
                "id",
                "username",
                "email",
                "first_name",
                "last_name",
            )
            .first()
        )

    def search(
        self,
        workspace_id: str,
        *,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        from django.contrib.auth import get_user_model
        from django.db.models import Q

        User = get_user_model()
        qs = User.objects.filter(workspaces__id=workspace_id)
        if query:
            qs = qs.filter(
                Q(username__icontains=query)
                | Q(email__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
            )
        return list(qs.values("id", "username", "email", "first_name", "last_name"))


class OrmPermissionToolRepository(PermissionToolRepository):
    def can_perform(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        action: str,
        scope_type: str = "workspace",
        scope_id: str | None = None,
    ) -> bool:
        from infrastructure.persistence.ai.models import AIPermissionGrant

        qs = AIPermissionGrant.objects.filter(
            workspace_id=workspace_id,
            principal_id=principal_id,
            status=AIPermissionGrant.STATUS_ACTIVE,
        )
        if scope_type != "workspace":
            qs = qs.filter(scope_type=scope_type)
        if scope_id:
            qs = qs.filter(scope_id=scope_id)
        for grant in qs:
            if "*" in (grant.actions or []) or action in (grant.actions or []):
                return True
        return False
