from __future__ import annotations

from django.db.models import Exists, OuterRef

from components.workspace.domain.policies.workspace_setup_policy_service import (
    WorkspaceSetupSnapshot,
)
from infrastructure.persistence.team.models import Team


class OrmWorkspaceSetupQueryRepository:
    def annotate_setup_state(self, queryset):
        return queryset.annotate(
            has_active_team=Exists(Team.objects.filter(workspace=OuterRef("pk"), status=Team.ACTIVE)),
        )

    def build_setup_snapshot(self, workspace) -> WorkspaceSetupSnapshot:
        return WorkspaceSetupSnapshot(
            workspace_id=workspace.id,
            workspace_name=workspace.workspace_name or "",
            has_contribution_means=self._has_contribution_means(workspace),
            has_story=bool((workspace.workspace_story or "").strip()),
            has_cover_photo=bool((workspace.photo_url or "").strip()),
            has_budget=self._has_budget(workspace),
            has_active_team=self._has_active_team(workspace),
        )

    @staticmethod
    def _has_contribution_means(workspace) -> bool:
        prefetched = getattr(workspace, "_prefetched_objects_cache", {})
        if "contribution_means" in prefetched:
            return bool(prefetched["contribution_means"])
        return workspace.contribution_means.exists()

    @staticmethod
    def _has_budget(workspace) -> bool:
        # Budgets are not part of the security product's workspace core.
        return False

    @staticmethod
    def _has_active_team(workspace) -> bool:
        annotated = getattr(workspace, "has_active_team", None)
        if annotated is not None:
            return bool(annotated)
        return Team.objects.filter(workspace=workspace, status=Team.ACTIVE).exists()
