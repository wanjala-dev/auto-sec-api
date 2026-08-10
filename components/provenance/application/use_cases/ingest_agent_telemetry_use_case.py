"""Ingest one batch of customer agent-runtime telemetry (ADR 0023 D1-D3).

The whole flow, in order, and every step fails closed:

1. **Consent.** Resolve the ACTIVE ``AgentTelemetrySource`` for this workspace.
   No row, wrong workspace, or a non-ACTIVE status ⇒ raise; nothing is written.
2. **Adapter.** Resolve the ``AgentTelemetryPort`` for the source's ``kind``.
   Unregistered kind ⇒ raise (never a silent no-op — the mistake
   ``triage.py``'s "routable without a tool is a silent no-op" warns about).
3. **Normalize.** The adapter parses the untrusted payload, refusing it outright
   if it carries prompt or tool-argument content.
4. **Allowlist.** Drop every record whose agent is not explicitly named on the
   source. We observe the agents the customer named, never every agent a feed
   happens to mention.
5. **Record.** Append to the existing provenance graph, idempotently.

Framework-free: no Django, no DRF, no ORM. The only collaborators are ports.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.provenance.application.ports.agent_activity_ledger_port import (
    AgentActivityIngestResult,
    AgentActivityLedgerPort,
)
from components.provenance.domain.errors import AgentTelemetrySourceUnavailableError

logger = logging.getLogger(__name__)


class IngestAgentTelemetryUseCase:
    def __init__(self, *, ledger: AgentActivityLedgerPort, adapters):
        # ``adapters`` is the AgentTelemetryProvider registry (resolve by kind).
        self._ledger = ledger
        self._adapters = adapters

    def execute(self, *, workspace_id: UUID, source_id: UUID, payload: dict) -> AgentActivityIngestResult:
        source = self._ledger.find_active_source(workspace_id=workspace_id, source_id=source_id)
        if source is None:
            # Deliberately does NOT distinguish "no such source" from "not yours"
            # from "disabled" — an ingest endpoint that leaks which source ids
            # exist in other tenants is an enumeration oracle.
            raise AgentTelemetrySourceUnavailableError("No active agent telemetry source for this workspace.")

        adapter = self._adapters.get(source.kind)
        batch = adapter.parse(payload, platform=source.platform)

        permitted = tuple(record for record in batch.records if source.permits(_agent_ref_of(record)))
        rejected = len(batch.records) - len(permitted)

        result = self._ledger.record(source=source, records=permitted)
        result = AgentActivityIngestResult(
            accepted=result.accepted,
            duplicates=result.duplicates,
            rejected_not_allowlisted=rejected,
            skipped=batch.skipped,
            actors_created=result.actors_created,
            resources_created=result.resources_created,
            skip_reasons=batch.skip_reasons,
        )

        # Counts only — never a record, an attribute value, or an agent identity.
        logger.info(
            "agent_telemetry_ingested workspace_id=%s source_id=%s kind=%s accepted=%s "
            "duplicates=%s rejected_not_allowlisted=%s skipped=%s",
            workspace_id,
            source_id,
            source.kind,
            result.accepted,
            result.duplicates,
            result.rejected_not_allowlisted,
            result.skipped,
        )
        return result


def _agent_ref_of(record) -> str:
    """The allowlist is written in the customer's own agent ids, not in URNs — so
    match on the URN's trailing segment rather than making them paste a URN."""
    parts = (record.agent_urn or "").split(":", 3)
    return parts[3] if len(parts) >= 4 else ""
