from __future__ import annotations

from django.db.models import Exists, OuterRef

from components.workspace.domain.policies.workspace_setup_policy_service import (
    WorkspaceSetupSnapshot,
)
from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.integrations.models import (
    AwsOrganizationConnection,
    SinkConnector,
)
from infrastructure.persistence.scanning.models import ScanRun
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import WorkspaceMembership


class OrmWorkspaceSetupQueryRepository:
    def annotate_setup_state(self, queryset):
        # List-view optimization (unchanged): a lightweight "does this workspace
        # have an active team" flag for workspace summaries.
        return queryset.annotate(
            has_active_team=Exists(Team.objects.filter(workspace=OuterRef("pk"), status=Team.ACTIVE)),
        )

    def build_setup_snapshot(self, workspace) -> WorkspaceSetupSnapshot:
        # The security getting-started funnel. Each is a cheap EXISTS against the
        # existing SSOT models — findings/scans/assets stay workspace-scoped.
        return WorkspaceSetupSnapshot(
            workspace_id=workspace.id,
            workspace_name=workspace.workspace_name or "",
            has_cloud_connected=self._has_cloud_connected(workspace),
            has_first_scan=self._has_first_scan(workspace),
            has_findings_triaged=self._has_findings_triaged(workspace),
            has_teammates_invited=self._has_teammates_invited(workspace),
            has_slack_connected=self._has_slack_connected(workspace),
        )

    @staticmethod
    def _has_cloud_connected(workspace) -> bool:
        return AwsOrganizationConnection.objects.filter(
            workspace=workspace, status=AwsOrganizationConnection.Status.CONNECTED
        ).exists()

    @staticmethod
    def _has_first_scan(workspace) -> bool:
        # A completed scan run, OR any finding (findings only exist because a scan
        # produced them — covers workspaces whose findings predate ScanRun tracking).
        return (
            ScanRun.objects.filter(workspace=workspace, status=ScanRun.Status.COMPLETED).exists()
            or Finding.objects.filter(workspace=workspace).exists()
        )

    @staticmethod
    def _has_findings_triaged(workspace) -> bool:
        # "Triaged" = at least one finding moved off the default "open" state.
        return Finding.objects.filter(workspace=workspace).exclude(status="open").exists()

    @staticmethod
    def _has_teammates_invited(workspace) -> bool:
        # More than the owner alone (exclude support-impersonation memberships).
        return WorkspaceMembership.objects.filter(workspace=workspace).exclude(is_impersonation=True).count() > 1

    @staticmethod
    def _has_slack_connected(workspace) -> bool:
        return SinkConnector.objects.filter(
            workspace=workspace, kind=SinkConnector.Kind.SLACK, is_enabled=True
        ).exists()
