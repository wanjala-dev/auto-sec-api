"""Backfill the provenance graph from AI-agent actions on findings.

In this platform an AI agent's durable action record is the in-finding
provenance trail: findings are ``Task`` rows (``source_type="ai.*"``), and the
shared board choreography (``_finding_processing.process_pending_finding``)
appends, each time an agent acts, an event to
``Task.metadata["provenance"]["events"]``:

    {"actor": "agent:triage_agent", "action": "proposed fix", "at": "...", "moved": true}

So an AI action attaches to the **finding the agent processed** (the entity its
tools mutate), not the workspace or an abstract run. We project each such event:

* the ``agent:<slug>`` actor -> a ``ProvenanceActor`` (``ai_agent`` / ``source="ai"``);
* the finding -> a ``ProvenanceResource`` (``resource_type="finding"``);
* the event -> a ``ProvenanceEvent`` keyed idempotently on ``<task_id>:<index>``.

Read-only against the finding board; idempotent — re-running projects no dupes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from infrastructure.persistence.project.models import Task
from infrastructure.persistence.provenance.models import (
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
)

logger = logging.getLogger(__name__)

_SOURCE = "ai"
_AGENT_PREFIX = "agent:"


def _upsert_ai_actor(workspace_id: UUID, slug: str, cache: dict) -> tuple[ProvenanceActor, bool]:
    if slug in cache:
        return cache[slug], False
    actor, created = ProvenanceActor.objects.get_or_create(
        workspace_id=workspace_id,
        source_system=_SOURCE,
        external_ref=slug,
        defaults={"actor_type": "ai_agent", "display_name": slug[:255]},
    )
    cache[slug] = actor
    return actor, created


def _upsert_finding_resource(workspace_id: UUID, task, cache: dict) -> tuple[ProvenanceResource, bool]:
    external_ref = f"project.task:{task.id}"[:512]
    if external_ref in cache:
        return cache[external_ref], False
    resource, created = ProvenanceResource.objects.get_or_create(
        workspace_id=workspace_id,
        source_system=_SOURCE,
        external_ref=external_ref,
        defaults={"resource_type": "finding", "display_name": (task.title or "finding")[:255]},
    )
    cache[external_ref] = resource
    return resource, created


def _parse_ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def backfill_from_ai_findings(*, workspace_id: UUID, batch_size: int = 500) -> dict[str, int]:
    """Project AI-agent finding actions into the graph.

    Returns per-kind counts of newly created rows. Idempotent: a second run
    returns zeros for the created kinds.
    """
    tasks = Task.objects.filter(workspace_id=workspace_id, source_type__startswith="ai.")
    counts = {"scanned": 0, "actors": 0, "resources": 0, "events": 0}
    actor_cache: dict = {}
    resource_cache: dict = {}

    for task in tasks.iterator(chunk_size=batch_size):
        counts["scanned"] += 1
        events = ((task.metadata or {}).get("provenance") or {}).get("events") or []
        resource = None
        for index, event in enumerate(events):
            actor_ref = event.get("actor") or ""
            if not actor_ref.startswith(_AGENT_PREFIX):
                continue  # only AI-agent actors here — human edits come from the audit source
            slug = actor_ref[len(_AGENT_PREFIX) :].strip()
            occurred_at = _parse_ts(event.get("at"))
            if not slug or occurred_at is None:
                continue

            actor, actor_created = _upsert_ai_actor(workspace_id, slug, actor_cache)
            counts["actors"] += int(actor_created)
            if resource is None:
                resource, resource_created = _upsert_finding_resource(workspace_id, task, resource_cache)
                counts["resources"] += int(resource_created)

            _, event_created = ProvenanceEvent.objects.get_or_create(
                workspace_id=workspace_id,
                origin=ProvenanceEvent.Origin.AI_ACTION,
                origin_id=f"{task.id}:{index}",
                defaults={
                    "actor": actor,
                    "resource": resource,
                    "action": (event.get("action") or "handled")[:128],
                    "occurred_at": occurred_at,
                    "source_system": _SOURCE,
                    "metadata": {"moved": bool(event.get("moved")), "source_type": task.source_type},
                },
            )
            counts["events"] += int(event_created)

    logger.info(
        "provenance_ai_backfill workspace_id=%s scanned=%s actors=%s resources=%s events=%s",
        workspace_id,
        counts["scanned"],
        counts["actors"],
        counts["resources"],
        counts["events"],
    )
    return counts
