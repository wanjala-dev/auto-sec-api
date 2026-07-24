"""Integration tests for the AI-finding -> provenance graph backfill.

Grounded in the real data shape: findings are ``Task`` rows (``source_type="ai.*"``)
whose ``metadata.provenance.events[]`` records each agent action, as written by
``_finding_processing.process_pending_finding``.
"""

from __future__ import annotations

import pytest

from components.provenance.infrastructure.services.ai_backfill_service import (
    backfill_from_ai_findings,
)
from infrastructure.persistence.project.models import Task
from infrastructure.persistence.provenance.models import (
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _finding(ws, team, user, *, source_type="ai.log_watch", events=None, title="Error in web"):
    metadata = {"payload": {}, "provenance": {"events": events or []}}
    return Task.objects.create(
        workspace=ws,
        team=team,
        created_by=user,
        title=title,
        source_type=source_type,
        metadata=metadata,
    )


def test_ai_actions_project_agent_actor_finding_resource_events(workspace_factory, team_factory, user_factory):
    ws = workspace_factory()
    team = team_factory(workspace=ws)
    user = user_factory()
    _finding(
        ws,
        team,
        user,
        events=[
            {"actor": "agent:triage_agent", "action": "proposed fix", "at": "2026-07-20T10:00:00", "moved": True},
            {"actor": "agent:triage_agent", "action": "posted comment", "at": "2026-07-20T10:01:00"},
        ],
    )

    counts = backfill_from_ai_findings(workspace_id=ws.id)

    assert counts == {"scanned": 1, "actors": 1, "resources": 1, "events": 2}
    actor = ProvenanceActor.objects.get(workspace=ws, source_system="ai")
    assert actor.actor_type == "ai_agent"
    assert actor.external_ref == "triage_agent"
    resource = ProvenanceResource.objects.get(workspace=ws, source_system="ai")
    assert resource.resource_type == "finding"
    assert ProvenanceEvent.objects.filter(workspace=ws, origin="ai_action").count() == 2


def test_ai_backfill_skips_non_agent_and_undated_events(workspace_factory, team_factory, user_factory):
    ws = workspace_factory()
    team = team_factory(workspace=ws)
    user = user_factory()
    _finding(
        ws,
        team,
        user,
        events=[
            {"actor": "user:someone", "action": "manual edit", "at": "2026-07-20T10:00:00"},
            {"actor": "agent:optimization_agent", "action": "no timestamp"},
        ],
    )
    # A finding with no provenance trail at all.
    _finding(ws, team, user, source_type="ai.optimization", events=[], title="Quiet finding")

    counts = backfill_from_ai_findings(workspace_id=ws.id)

    assert counts == {"scanned": 2, "actors": 0, "resources": 0, "events": 0}


def test_ai_backfill_is_idempotent(workspace_factory, team_factory, user_factory):
    ws = workspace_factory()
    team = team_factory(workspace=ws)
    user = user_factory()
    _finding(
        ws,
        team,
        user,
        events=[{"actor": "agent:triage_agent", "action": "proposed fix", "at": "2026-07-20T10:00:00"}],
    )

    first = backfill_from_ai_findings(workspace_id=ws.id)
    second = backfill_from_ai_findings(workspace_id=ws.id)

    assert first == {"scanned": 1, "actors": 1, "resources": 1, "events": 1}
    assert second == {"scanned": 1, "actors": 0, "resources": 0, "events": 0}
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 1
