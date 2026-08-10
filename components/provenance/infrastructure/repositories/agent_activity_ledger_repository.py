"""ORM adapter for :class:`AgentActivityLedgerPort` — writes into the EXISTING graph.

No new store (ADR 0004 hub-and-spoke, ADR 0023 D1): a customer agent becomes a
``ProvenanceActor`` (``ai_agent`` / ``agent_runtime``), the thing it touched a
``ProvenanceResource``, and the action a ``ProvenanceEvent`` keyed idempotently on
``(workspace, origin=agent_runtime, origin_id=<trace>:<span>)``.

``AccessGrant`` rows — the *potential* half — are deliberately not written here.
That is the capability axis and it is read from the customer's grant surface
(MCP ``tools/list``, restricted-key permissions, IdP scopes), never inferred from
behaviour. Inferring a grant from an observed action would quietly turn "it did
this" into "it may do this", which is exactly the claim we must not fabricate.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from components.provenance.application.ports.agent_activity_ledger_port import (
    AgentActivityIngestResult,
    AgentActivityLedgerPort,
    ConsentedTelemetrySource,
)
from infrastructure.persistence.provenance.models import (
    AgentTelemetrySource,
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
)

logger = logging.getLogger(__name__)

_SOURCE_SYSTEM = "agent_runtime"


class AgentActivityLedgerRepository(AgentActivityLedgerPort):
    def find_active_source(self, *, workspace_id, source_id) -> ConsentedTelemetrySource | None:
        row = (
            AgentTelemetrySource.objects.filter(
                id=source_id,
                workspace_id=workspace_id,
                status=AgentTelemetrySource.Status.ACTIVE,
            )
            .only("id", "workspace_id", "kind", "platform", "agent_allowlist")
            .first()
        )
        if row is None:
            return None
        allowlist = row.agent_allowlist if isinstance(row.agent_allowlist, list) else []
        return ConsentedTelemetrySource(
            id=row.id,
            workspace_id=row.workspace_id,
            kind=row.kind,
            platform=row.platform,
            agent_allowlist=tuple(str(entry) for entry in allowlist),
        )

    @transaction.atomic
    def record(self, *, source: ConsentedTelemetrySource, records) -> AgentActivityIngestResult:
        actor_cache: dict[str, ProvenanceActor] = {}
        resource_cache: dict[str, ProvenanceResource] = {}
        accepted = duplicates = actors_created = resources_created = 0

        for record in records:
            actor, actor_created = self._upsert_actor(source, record, actor_cache)
            actors_created += int(actor_created)
            resource, resource_created = self._upsert_resource(source, record, resource_cache)
            resources_created += int(resource_created)

            _, event_created = ProvenanceEvent.objects.get_or_create(
                workspace_id=source.workspace_id,
                origin=ProvenanceEvent.Origin.AGENT_RUNTIME,
                origin_id=record.origin_id,
                defaults={
                    "actor": actor,
                    "resource": resource,
                    "action": record.action,
                    "occurred_at": record.occurred_at,
                    "source_system": _SOURCE_SYSTEM,
                    "metadata": {
                        "telemetry_source_id": str(source.id),
                        "platform": source.platform,
                        "tool": record.tool_name,
                        "outcome": record.outcome,
                        "trace_id": record.trace_id,
                        "span_id": record.span_id,
                        # Self-reported by the customer's runtime. Attributable,
                        # not verified — no telemetry standard carries a
                        # credential, and Stripe does not expose the acting API
                        # key per request programmatically (Dashboard-only).
                        "identity_assertion": "self_reported",
                        **record.attributes,
                    },
                },
            )
            accepted += int(event_created)
            duplicates += int(not event_created)

        AgentTelemetrySource.objects.filter(id=source.id).update(last_ingest_at=timezone.now(), last_error="")

        return AgentActivityIngestResult(
            accepted=accepted,
            duplicates=duplicates,
            actors_created=actors_created,
            resources_created=resources_created,
        )

    def _upsert_actor(self, source, record, cache):
        if record.agent_urn in cache:
            return cache[record.agent_urn], False
        actor, created = ProvenanceActor.objects.get_or_create(
            workspace_id=source.workspace_id,
            source_system=_SOURCE_SYSTEM,
            external_ref=record.agent_urn,
            defaults={
                "actor_type": "ai_agent",
                # Display the customer's own agent id, not the URN.
                "display_name": record.agent_urn.rsplit(":", 1)[-1][:255],
            },
        )
        cache[record.agent_urn] = actor
        return actor, created

    def _upsert_resource(self, source, record, cache):
        if record.resource_ref in cache:
            return cache[record.resource_ref], False
        resource, created = ProvenanceResource.objects.get_or_create(
            workspace_id=source.workspace_id,
            source_system=_SOURCE_SYSTEM,
            external_ref=record.resource_ref,
            defaults={
                "resource_type": record.resource_type,
                "display_name": record.resource_ref[:255],
            },
        )
        cache[record.resource_ref] = resource
        return resource, created
