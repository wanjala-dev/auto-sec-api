"""
ORM adapters for cross-context queries the agents context needs.

Each class implements one of the query ports defined in
``components.agents.application.ports.cross_context_query_port``.
All Django ORM imports are lazy so the module can be imported safely at
composition-root time without pulling in the entire model graph.
"""

from __future__ import annotations

import logging
from typing import Any

from components.agents.application.ports.cross_context_query_port import (
    DocumentQueryPort,
    FileRepositoryPort,
    ProjectQueryPort,
    TeamQueryPort,
    UserQueryPort,
    WorkspaceAiToggleStatus,
    WorkspaceQueryPort,
)

logger = logging.getLogger(__name__)


class OrmWorkspaceQueryAdapter(WorkspaceQueryPort):
    def get_by_id(self, workspace_id: str) -> Any | None:
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(id=workspace_id).first()

    def get_by_id_unfiltered(self, workspace_id: str) -> Any | None:
        # Base manager (unfiltered) so an inactive/soft-deleted workspace is
        # still returned — mirrors the prior inline ``Workspace._base_manager``
        # read in ``detector_cycle``.
        from infrastructure.persistence.workspaces.models import Workspace

        manager = getattr(Workspace, "_base_manager", None) or Workspace.objects
        return manager.filter(id=str(workspace_id)).first()

    def exists(self, workspace_id: str) -> bool:
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(id=workspace_id).exists()

    def get_ai_toggle_status(self, workspace_id: str) -> WorkspaceAiToggleStatus:
        # Read via the model's BASE manager (unfiltered) so an inactive/
        # soft-deleted workspace is still found and its AI toggle still read —
        # the kill-switch report must reflect a halted workspace, not treat it as
        # absent. Mirrors the prior inline ``Workspace._base_manager`` read.
        try:
            from infrastructure.persistence.workspaces.models import Workspace

            manager = getattr(Workspace, "_base_manager", None) or Workspace.objects
            row = manager.filter(id=str(workspace_id)).only("id", "ai_teammate_enabled").first()
        except Exception:
            logger.exception("workspace ai-toggle read failed workspace_id=%s", workspace_id)
            return WorkspaceAiToggleStatus(found=False, ai_teammate_enabled=False)
        if row is None:
            return WorkspaceAiToggleStatus(found=False, ai_teammate_enabled=False)
        return WorkspaceAiToggleStatus(found=True, ai_teammate_enabled=bool(row.ai_teammate_enabled))


class OrmTeamQueryAdapter(TeamQueryPort):
    def get_by_id(self, team_id: str, *, active_only: bool = True) -> Any | None:
        from infrastructure.persistence.team.models import Team

        qs = Team.objects.filter(id=team_id)
        if active_only:
            qs = qs.filter(status=Team.ACTIVE)
        return qs.first()


class OrmProjectQueryAdapter(ProjectQueryPort):
    def get_project_by_id(self, project_id: str, *, team: Any) -> Any | None:
        from infrastructure.persistence.project.models import Project

        return Project.objects.filter(id=project_id, team=team).first()

    def get_column_by_id(self, column_id: str, *, team: Any) -> Any | None:
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
    def get_with_chunks(self, document_id: str) -> Any | None:
        from django.db.models import Prefetch

        from infrastructure.persistence.ai.models import Document, DocumentChunk

        return (
            Document.objects.prefetch_related(
                Prefetch("chunks", queryset=DocumentChunk.objects.order_by("chunk_index"))
            )
            .filter(id=document_id)
            .first()
        )
