"""Repository for WorkspaceLogSource (ADR 0008 Phase 3) — the ONLY ORM slot for
the log-source catalog. Controllers/services never touch persistence directly.
"""

from __future__ import annotations

from django.utils import timezone

from infrastructure.persistence.integrations.models import WorkspaceLogSource


class LogSourceRepository:
    """ORM access for a workspace's configured log sources."""

    def list_for_workspace(self, workspace_id) -> list[WorkspaceLogSource]:
        return list(WorkspaceLogSource.objects.filter(workspace_id=workspace_id).order_by("kind", "created_at"))

    def get(self, workspace_id, source_id) -> WorkspaceLogSource | None:
        return WorkspaceLogSource.objects.filter(id=source_id, workspace_id=workspace_id).first()

    def active_s3_source_for_connection(self, connection) -> WorkspaceLogSource | None:
        """The active S3 log source a connection reads through (ADR 0008 D7).

        The S3 *location* lives on this owned row, so a connection re-verify can no
        longer blank where logs are read from (the "logs silently stopped"
        regression). Oldest-first is stable when a workspace has more than one."""
        return (
            WorkspaceLogSource.objects.filter(
                workspace_id=connection.workspace_id,
                kind=WorkspaceLogSource.Kind.S3,
                status=WorkspaceLogSource.Status.ACTIVE,
                config__aws_connection_id=str(connection.id),
            )
            .order_by("created_at")
            .first()
        )

    def find_connection_for_source(self, source):
        """Resolve the AWS connection an S3/CloudWatch source reads through — the
        assume-role identity referenced by ``config['aws_connection_id']``. Returns
        ``None`` when the source references no / a missing connection."""
        from infrastructure.persistence.integrations.models import AwsOrganizationConnection

        conn_id = str((source.config or {}).get("aws_connection_id") or "")
        if not conn_id:
            return None
        return AwsOrganizationConnection.objects.filter(id=conn_id, workspace_id=source.workspace_id).first()

    def create(
        self,
        *,
        workspace_id,
        kind: str,
        name: str,
        config: dict,
        status: str = WorkspaceLogSource.Status.DRAFT,
    ) -> WorkspaceLogSource:
        return WorkspaceLogSource.objects.create(
            workspace_id=workspace_id,
            kind=kind,
            name=name,
            config=config or {},
            status=status,
        )

    def update(
        self,
        source: WorkspaceLogSource,
        *,
        name: str | None = None,
        config: dict | None = None,
        status: str | None = None,
    ) -> WorkspaceLogSource:
        """Partial update — only fields explicitly provided are written."""
        changed: list[str] = []
        if name is not None and name != source.name:
            source.name = name
            changed.append("name")
        if config is not None and config != source.config:
            source.config = config
            changed.append("config")
        if status is not None and status != source.status:
            source.status = status
            changed.append("status")
        if changed:
            source.save(update_fields=[*changed, "updated_at"])
        return source

    def mark_verified(self, source: WorkspaceLogSource) -> WorkspaceLogSource:
        source.status = WorkspaceLogSource.Status.ACTIVE
        source.last_verified_at = timezone.now()
        source.last_error = ""
        source.save(update_fields=["status", "last_verified_at", "last_error", "updated_at"])
        return source

    def mark_error(self, source: WorkspaceLogSource, message: str) -> WorkspaceLogSource:
        source.status = WorkspaceLogSource.Status.ERROR
        source.last_error = (message or "")[:2000]
        source.save(update_fields=["status", "last_error", "updated_at"])
        return source

    def delete(self, source: WorkspaceLogSource) -> None:
        source.delete()
