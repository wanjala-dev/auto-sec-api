"""Integration tests for the agent-runtime telemetry ingest endpoint (ADR 0023).

Exercises the whole consent→normalize→ledger path: a well-formed batch creates
the expected provenance rows; unauthenticated, cross-workspace, oversized,
malformed, non-allowlisted and content-bearing input are all refused; and the
capability is dark behind its own flag.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from infrastructure.persistence.core.models import FeatureFlag
from infrastructure.persistence.provenance.models import (
    AccessGrant,
    AgentTelemetrySource,
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_FLAG = "feature.agent_runtime_accountability"


def _enable_flag():
    FeatureFlag.objects.get_or_create(key=_FLAG, defaults={"default_enabled": True})


def _source(ws, *, agents=("invoice-bot",), status=AgentTelemetrySource.Status.ACTIVE):
    return AgentTelemetrySource.objects.create(
        workspace=ws,
        kind=AgentTelemetrySource.Kind.OTLP_JSON,
        platform="vercel",
        agent_allowlist=list(agents),
        status=status,
    )


def _url(ws, source):
    return reverse(
        "provenance-agent-telemetry-ingest",
        kwargs={"workspace_id": str(ws.id), "source_id": str(source.id)},
    )


def _client(ws=None):
    client = APIClient()
    if ws is not None:
        client.force_authenticate(user=ws.workspace_owner)
    return client


def _attr(key, value):
    return {"key": key, "value": {"stringValue": value}}


def _payload(*, agent="invoice-bot", span_id="051581bf3cb55c13", extra_attributes=()):
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "5b8aa5a2d2c872e8321cf37308d69df2",
                                "spanId": span_id,
                                "name": "execute_tool charge_card",
                                "startTimeUnixNano": "1754700000000000000",
                                "status": {"code": 1},
                                "attributes": [
                                    _attr("gen_ai.agent.id", agent),
                                    _attr("gen_ai.tool.name", "charge_card"),
                                    _attr("gen_ai.operation.name", "execute_tool"),
                                    _attr("server.address", "api.stripe.com"),
                                    *extra_attributes,
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }


# ── happy path ────────────────────────────────────────────────────────────────


def test_well_formed_batch_creates_provenance_rows(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws)

    resp = _client(ws).post(_url(ws, source), _payload(), format="json")

    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data == {
        "accepted": 1,
        "duplicates": 0,
        "rejected_not_allowlisted": 0,
        "skipped": 0,
        "actors_created": 1,
        "resources_created": 1,
        "skip_reasons": {},
    }

    actor = ProvenanceActor.objects.get(workspace=ws, source_system="agent_runtime")
    assert actor.actor_type == "ai_agent"
    assert actor.external_ref == "urn:agent:vercel:invoice-bot"
    assert actor.display_name == "invoice-bot"

    resource = ProvenanceResource.objects.get(workspace=ws, source_system="agent_runtime")
    assert resource.external_ref == "api.stripe.com"
    # Stamped by the existing pre_save bridge — no ingester-specific URN logic.
    assert resource.asset_urn == "urn:agent_runtime:api.stripe.com"

    event = ProvenanceEvent.objects.get(workspace=ws, origin="agent_runtime")
    assert event.actor_id == actor.id
    assert event.resource_id == resource.id
    assert event.action == "execute_tool"
    assert event.origin_id == "5b8aa5a2d2c872e8321cf37308d69df2:051581bf3cb55c13"
    assert event.metadata["tool"] == "charge_card"
    assert event.metadata["outcome"] == "ok"
    # Honest labelling: the identity was asserted by the customer's runtime.
    assert event.metadata["identity_assertion"] == "self_reported"

    source.refresh_from_db()
    assert source.last_ingest_at is not None


def test_ingest_is_idempotent_on_trace_and_span(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws)
    client = _client(ws)

    client.post(_url(ws, source), _payload(), format="json")
    resp = client.post(_url(ws, source), _payload(), format="json")

    assert resp.json()["data"] == {
        "accepted": 0,
        "duplicates": 1,
        "rejected_not_allowlisted": 0,
        "skipped": 0,
        "actors_created": 0,
        "resources_created": 0,
        "skip_reasons": {},
    }
    assert ProvenanceEvent.objects.filter(workspace=ws, origin="agent_runtime").count() == 1


def test_ingest_writes_the_did_axis_only_never_a_grant(workspace_factory):
    """``AccessGrant`` is the CAN axis and is read from the customer's grant
    surface — inferring one from observed behaviour would fabricate a claim."""
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws)

    _client(ws).post(_url(ws, source), _payload(), format="json")

    assert AccessGrant.objects.filter(workspace=ws).count() == 0


# ── consent + tenancy ─────────────────────────────────────────────────────────


def test_unauthenticated_request_is_refused(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws)

    resp = _client().post(_url(ws, source), _payload(), format="json")

    assert resp.status_code in (401, 403)
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 0


def test_non_member_cannot_ingest(workspace_factory, user_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws)
    client = APIClient()
    client.force_authenticate(user=user_factory())

    resp = client.post(_url(ws, source), _payload(), format="json")

    assert resp.status_code == 403
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 0


def test_source_from_another_workspace_does_not_resolve(workspace_factory):
    """A valid source id belonging to another tenant must read as 'not found',
    not as that tenant's consent row."""
    owner_ws = workspace_factory()
    attacker_ws = workspace_factory()
    _enable_flag()
    victim_source = _source(owner_ws)

    url = reverse(
        "provenance-agent-telemetry-ingest",
        kwargs={"workspace_id": str(attacker_ws.id), "source_id": str(victim_source.id)},
    )
    resp = _client(attacker_ws).post(url, _payload(), format="json")

    assert resp.status_code == 404
    assert ProvenanceEvent.objects.filter(workspace=owner_ws).count() == 0
    assert ProvenanceEvent.objects.filter(workspace=attacker_ws).count() == 0


def test_unknown_source_is_404(workspace_factory):
    ws = workspace_factory()
    _enable_flag()

    url = reverse(
        "provenance-agent-telemetry-ingest",
        kwargs={"workspace_id": str(ws.id), "source_id": str(uuid4())},
    )
    resp = _client(ws).post(url, _payload(), format="json")

    assert resp.status_code == 404


def test_draft_source_ingests_nothing(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws, status=AgentTelemetrySource.Status.DRAFT)

    resp = _client(ws).post(_url(ws, source), _payload(), format="json")

    assert resp.status_code == 404
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 0


def test_agent_outside_the_allowlist_is_rejected(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws, agents=("invoice-bot",))

    resp = _client(ws).post(_url(ws, source), _payload(agent="shadow-bot"), format="json")

    assert resp.status_code == 202
    assert resp.json()["data"]["rejected_not_allowlisted"] == 1
    assert resp.json()["data"]["accepted"] == 0
    assert ProvenanceActor.objects.filter(workspace=ws).count() == 0


def test_empty_allowlist_is_fail_closed_not_a_wildcard(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws, agents=())

    resp = _client(ws).post(_url(ws, source), _payload(), format="json")

    assert resp.json()["data"]["accepted"] == 0
    assert resp.json()["data"]["rejected_not_allowlisted"] == 1
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 0


# ── untrusted input ───────────────────────────────────────────────────────────


def test_content_bearing_payload_is_refused(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws)
    payload = _payload(extra_attributes=[_attr("ai.prompt.messages", "card 4242 4242 4242 4242")])

    resp = _client(ws).post(_url(ws, source), payload, format="json")

    assert resp.status_code == 422
    assert "ai.prompt.messages" in resp.json()["error"]
    assert "4242" not in resp.json()["error"]
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 0


def test_malformed_payload_is_400(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws)

    resp = _client(ws).post(_url(ws, source), {"spans": []}, format="json")

    assert resp.status_code == 400
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 0


def test_oversized_body_is_413(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    source = _source(ws)
    client = _client(ws)

    resp = client.post(
        _url(ws, source),
        _payload(),
        format="json",
        CONTENT_LENGTH=str(2_000_000),
    )

    assert resp.status_code == 413
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 0


# ── darkness ──────────────────────────────────────────────────────────────────


def test_endpoint_is_gated_by_its_own_sibling_flag():
    """Deterministic wiring check: the ingest endpoint declares its OWN dark flag
    (never a reuse of feature.provenance_graph), plus membership + a dedicated
    throttle bucket. (Runtime deny can't be exercised in DEBUG/test where flags
    fail open; RequiresFeatureFlag's own runtime is platform-tested.)"""
    from rest_framework.throttling import ScopedRateThrottle

    from components.provenance.api.controller import AgentTelemetryIngestView
    from components.shared_platform.api.permissions import HasWorkspaceMembership, RequiresFeatureFlag

    assert AgentTelemetryIngestView.feature_flag_key == _FLAG
    assert AgentTelemetryIngestView.feature_flag_key != "feature.provenance_graph"
    assert RequiresFeatureFlag in AgentTelemetryIngestView.permission_classes
    assert HasWorkspaceMembership in AgentTelemetryIngestView.permission_classes
    assert AgentTelemetryIngestView.throttle_scope == "agent_telemetry_ingest"
    assert ScopedRateThrottle in AgentTelemetryIngestView.throttle_classes


def test_flag_is_seeded_dark_and_prod_disabled():
    from components.shared_platform.cli.management.commands.seed_feature_flags import (
        DEFAULT_FLAGS,
        PROD_DISABLED_FLAGS,
    )

    seeded = {key: default for key, default, _desc in DEFAULT_FLAGS}
    assert seeded[_FLAG] is False
    assert _FLAG in PROD_DISABLED_FLAGS
