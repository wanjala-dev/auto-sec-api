"""ORM adapter implementing :class:`AccessGraphBackfillPort`.

Thin bridge over the three backfill services — the port-facing surface the
application layer drives, keeping the concrete services an infrastructure
detail. Imports are local to each method so the Celery app / detector cycle can
load this module before the app registry is fully ready.
"""

from __future__ import annotations

from uuid import UUID

from components.provenance.application.ports.access_graph_backfill_port import (
    AccessGraphBackfillPort,
)


class DjangoAccessGraphBackfillAdapter(AccessGraphBackfillPort):
    def backfill_from_audit_log(self, *, workspace_id: UUID) -> dict[str, int]:
        from components.provenance.infrastructure.services.audit_backfill_service import (
            backfill_from_audit_log,
        )

        return backfill_from_audit_log(workspace_id=workspace_id)

    def backfill_from_memberships(self, *, workspace_id: UUID) -> dict[str, int]:
        from components.provenance.infrastructure.services.identity_backfill_service import (
            backfill_from_memberships,
        )

        return backfill_from_memberships(workspace_id=workspace_id)

    def backfill_from_ai_findings(self, *, workspace_id: UUID) -> dict[str, int]:
        from components.provenance.infrastructure.services.ai_backfill_service import (
            backfill_from_ai_findings,
        )

        return backfill_from_ai_findings(workspace_id=workspace_id)
