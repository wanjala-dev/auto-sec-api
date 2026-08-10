"""``AgentActivityLedgerPort`` — everything the ingest use case needs from persistence.

Two responsibilities, both on the *consent-then-write* path:

1. **Resolve the consent row** for a ``(workspace, source)`` pair — fail-closed.
2. **Record** normalized records into the EXISTING provenance graph
   (``ProvenanceActor`` / ``ProvenanceResource`` / ``ProvenanceEvent``).

There is no new findings store and no per-platform table: ADR 0004's hub-and-spoke
rule and ADR 0023 D1 both forbid it, and the graph already carries ``ai_agent`` in
``ActorType`` and a granted-vs-used model in ``AccessGrant`` vs ``ProvenanceEvent``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.provenance.domain.entities.agent_activity_entity import AgentActivityRecord


@dataclass(frozen=True)
class ConsentedTelemetrySource:
    """The consent boundary, read out of persistence and into the core.

    ``agent_allowlist`` is fail-closed by construction: :meth:`permits` returns
    ``False`` for an empty list. An empty allowlist means "observe nothing", never
    "observe everything" — the exact inversion ADR 0021 D3 refused.
    """

    id: UUID
    workspace_id: UUID
    kind: str
    platform: str
    agent_allowlist: tuple[str, ...] = ()

    def permits(self, agent_ref: str) -> bool:
        ref = (agent_ref or "").strip().lower()
        if not ref:
            return False
        return ref in {entry.strip().lower() for entry in self.agent_allowlist if entry}


@dataclass(frozen=True)
class AgentActivityIngestResult:
    """Per-batch counts. Deliberately free of any record detail — this is what the
    HTTP response and the log line carry, and neither may leak observed content."""

    accepted: int = 0
    duplicates: int = 0
    rejected_not_allowlisted: int = 0
    skipped: int = 0
    actors_created: int = 0
    resources_created: int = 0
    skip_reasons: dict = field(default_factory=dict)


class AgentActivityLedgerPort:
    """Interface (structural) for the provenance-graph write path."""

    def find_active_source(self, *, workspace_id: UUID, source_id: UUID) -> ConsentedTelemetrySource | None:
        """Return the ACTIVE source for this workspace, or ``None``.

        MUST scope on ``workspace_id`` as well as ``source_id`` so a valid source
        id from another tenant resolves to ``None`` rather than to that tenant's
        consent row.
        """
        raise NotImplementedError

    def record(
        self,
        *,
        source: ConsentedTelemetrySource,
        records: tuple[AgentActivityRecord, ...],
    ) -> AgentActivityIngestResult:
        """Upsert actors/resources and append events. Idempotent on
        ``(workspace, origin, origin_id)`` — re-POSTing a batch creates nothing."""
        raise NotImplementedError
