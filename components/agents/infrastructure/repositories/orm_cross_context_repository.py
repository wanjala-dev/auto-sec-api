"""
ORM adapters for cross-context queries the agents context needs.

Each class implements one of the query ports defined in
``components.agents.application.ports.cross_context_query_port``.
All Django ORM imports are lazy so the module can be imported safely at
composition-root time without pulling in the entire model graph.
"""

from __future__ import annotations

from typing import Any, Optional

from components.agents.application.ports.cross_context_query_port import (
    DocumentQueryPort,
    FileRepositoryPort,
    ProjectQueryPort,
    TeamQueryPort,
    UserQueryPort,
    WorkspaceQueryPort,
)


class OrmWorkspaceQueryAdapter(WorkspaceQueryPort):

    def get_by_id(self, workspace_id: str) -> Optional[Any]:
        from infrastructure.persistence.workspaces.models import Workspace
        return Workspace.objects.filter(id=workspace_id).first()

    def exists(self, workspace_id: str) -> bool:
        from infrastructure.persistence.workspaces.models import Workspace
        return Workspace.objects.filter(id=workspace_id).exists()


class OrmTeamQueryAdapter(TeamQueryPort):

    def get_by_id(self, team_id: str, *, active_only: bool = True) -> Optional[Any]:
        from infrastructure.persistence.team.models import Team
        qs = Team.objects.filter(id=team_id)
        if active_only:
            qs = qs.filter(status=Team.ACTIVE)
        return qs.first()


class OrmProjectQueryAdapter(ProjectQueryPort):

    def get_project_by_id(self, project_id: str, *, team: Any) -> Optional[Any]:
        from infrastructure.persistence.project.models import Project
        return Project.objects.filter(id=project_id, team=team).first()

    def get_column_by_id(self, column_id: str, *, team: Any) -> Optional[Any]:
        from infrastructure.persistence.project.models import Column
        return Column.objects.filter(id=column_id, team=team).first()

    def list_columns(self, *, team: Any, workspace: Any, active_only: bool = True) -> Any:
        from infrastructure.persistence.project.models import Column
        qs = Column.objects.filter(team=team, workspace=workspace)
        if active_only:
            qs = qs.filter(is_deleted=False)
        return qs


class OrmUserQueryAdapter(UserQueryPort):

    def get_by_ids(self, user_ids: list[str]) -> list[Any]:
        from infrastructure.persistence.users.models import CustomUser
        return list(CustomUser.objects.filter(id__in=user_ids))


class OrmFileRepositoryAdapter(FileRepositoryPort):

    def get_by_id(self, file_id: str, *, owner: Any) -> Any:
        from infrastructure.persistence.uploads.models import File
        return File.objects.get(id=file_id, owner=owner)

    def update_processing_status(self, file: Any, *, status: str) -> None:
        file.processing_status = status
        file.save()


class OrmDocumentQueryAdapter(DocumentQueryPort):

    def get_with_chunks(self, document_id: str) -> Optional[Any]:
        from infrastructure.persistence.ai.models import Document, DocumentChunk
        from django.db.models import Prefetch
        return (
            Document.objects
            .prefetch_related(
                Prefetch("chunks", queryset=DocumentChunk.objects.order_by("chunk_index"))
            )
            .filter(id=document_id)
            .first()
        )
