"""Use case: list the audit trail for an entire workspace.

The auditor read surface. Unlike ``GetEntityHistoryUseCase`` (one
entity), this returns every tracked field change in a tenant, newest
first, with optional narrowing and pagination — the "who changed what,
when" feed a security reviewer works from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from components.audit.application.ports.audit_log_port import AuditLogPort
from components.audit.domain.entities.audit_entry_entity import AuditEntry


@dataclass
class GetWorkspaceHistoryUseCase:
    audit_log: AuditLogPort

    def execute(
        self,
        *,
        workspace_id: str,
        entity_type: str | None = None,
        field_name: str | None = None,
        actor_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]:
        """Return ``(entries, total_count)`` for the workspace, newest first.

        ``workspace_id`` is mandatory and scopes the result to one
        tenant — the REST adapter enforces membership on that same
        workspace via ``IsAuditWorkspaceMember`` before this runs. The
        remaining arguments narrow the feed; ``total_count`` is the
        filtered count before pagination so the caller can render page
        controls.
        """

        return self.audit_log.list_for_workspace(
            workspace_id=workspace_id,
            entity_type=entity_type,
            field_name=field_name,
            actor_id=actor_id,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
