"""Unit tests for the OTLP/HTTP JSON agent-telemetry adapter (no DB, no framework).

Covers the three things that must never regress: the happy-path normalization,
the metadata-only refusal, and the fail-closed skips.
"""

from __future__ import annotations

import pytest

from components.provenance.application.providers.agent_telemetry_provider import AgentTelemetryProvider
from components.provenance.domain.entities.agent_activity_entity import MAX_ORIGIN_ID_LENGTH
from components.provenance.domain.errors import (
    AgentTelemetryContentRejectedError,
    AgentTelemetryPayloadError,
    UnsupportedAgentTelemetryKindError,
)
from components.provenance.domain.value_objects.agent_urn import AgentUrn
from components.provenance.infrastructure.adapters.agent_telemetry.otlp_json_agent_telemetry_adapter import (
    MAX_ATTRIBUTE_VALUE_LENGTH,
    MAX_SPANS_PER_BATCH,
    OtlpJsonAgentTelemetryAdapter,
)

pytestmark = pytest.mark.unit


def _attr(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


def _span(**overrides) -> dict:
    span = {
        "traceId": "5b8aa5a2d2c872e8321cf37308d69df2",
        "spanId": "051581bf3cb55c13",
        "name": "execute_tool charge_card",
        "startTimeUnixNano": "1754700000000000000",
        "status": {"code": 1},
        "attributes": [
            _attr("gen_ai.agent.id", "invoice-bot"),
            _attr("gen_ai.tool.name", "charge_card"),
            _attr("gen_ai.operation.name", "execute_tool"),
            _attr("server.address", "api.stripe.com"),
        ],
    }
    span.update(overrides)
    return span


def _payload(*spans, resource_attributes=None) -> dict:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": resource_attributes or []},
                "scopeSpans": [{"spans": list(spans)}],
            }
        ]
    }


def test_normalizes_a_tool_span_into_a_record():
    batch = OtlpJsonAgentTelemetryAdapter().parse(_payload(_span()), platform="vercel")

    assert batch.skipped == 0
    assert len(batch.records) == 1
    record = batch.records[0]
    assert record.agent_urn == "urn:agent:vercel:invoice-bot"
    assert record.resource_ref == "api.stripe.com"
    assert record.resource_type == "network_endpoint"
    assert record.action == "execute_tool"
    assert record.tool_name == "charge_card"
    assert record.outcome == "ok"
    assert record.origin_id == "5b8aa5a2d2c872e8321cf37308d69df2:051581bf3cb55c13"
    assert record.occurred_at.tzinfo is not None


def test_agent_identity_falls_back_to_resource_service_name():
    span = _span(attributes=[_attr("gen_ai.tool.name", "lookup"), _attr("server.address", "db.internal")])
    payload = _payload(span, resource_attributes=[_attr("service.name", "support-bot")])

    batch = OtlpJsonAgentTelemetryAdapter().parse(payload, platform="vercel")

    assert batch.records[0].agent_urn == "urn:agent:vercel:support-bot"


def test_tool_only_span_falls_back_to_an_agent_tool_resource():
    span = _span(attributes=[_attr("gen_ai.agent.id", "invoice-bot"), _attr("gen_ai.tool.name", "send_email")])

    batch = OtlpJsonAgentTelemetryAdapter().parse(_payload(span), platform="vercel")

    assert batch.records[0].resource_ref == "tool:send_email"
    assert batch.records[0].resource_type == "agent_tool"


@pytest.mark.parametrize(
    "content_key",
    [
        "gen_ai.input.messages",
        "gen_ai.prompt.0.content",
        "gen_ai.tool.call.arguments",
        "ai.prompt.messages",
        "ai.toolCall.args",
        "ai.response.text",
        "input.value",
    ],
)
def test_content_bearing_payload_is_refused_not_stripped(content_key):
    span = _span(attributes=[*_span()["attributes"], _attr(content_key, "4242 4242 4242 4242")])

    with pytest.raises(AgentTelemetryContentRejectedError) as excinfo:
        OtlpJsonAgentTelemetryAdapter().parse(_payload(span), platform="vercel")

    # The offending KEY is surfaced so the customer can fix their exporter; the
    # VALUE must never appear in the message.
    assert content_key in str(excinfo.value)
    assert "4242" not in str(excinfo.value)


def test_content_hidden_in_span_events_is_also_refused():
    span = _span(events=[{"name": "prompt", "attributes": [_attr("gen_ai.prompt", "secret")]}])

    with pytest.raises(AgentTelemetryContentRejectedError):
        OtlpJsonAgentTelemetryAdapter().parse(_payload(span), platform="vercel")


def test_content_on_the_resource_is_also_refused():
    payload = _payload(_span(), resource_attributes=[_attr("gen_ai.output.messages", "secret")])

    with pytest.raises(AgentTelemetryContentRejectedError):
        OtlpJsonAgentTelemetryAdapter().parse(payload, platform="vercel")


def test_unattributable_span_is_skipped_never_invented():
    span = _span(attributes=[_attr("server.address", "api.stripe.com")])

    batch = OtlpJsonAgentTelemetryAdapter().parse(_payload(span), platform="vercel")

    assert batch.records == ()
    assert batch.skipped == 1
    assert batch.skip_reasons == {"no_agent_identity": 1}


def test_span_without_a_timestamp_is_skipped():
    batch = OtlpJsonAgentTelemetryAdapter().parse(_payload(_span(startTimeUnixNano="not-a-number")), platform="vercel")

    assert batch.records == ()
    assert batch.skip_reasons == {"no_timestamp": 1}


def test_a_long_trace_id_keeps_every_span_distinct():
    """Identities are read WHOLE, so two spans of one long trace stay two spans.

    The adapter's value cap is a storage bound; applying it (or any other trim)
    while reading an identity is how spans silently merge.
    """
    trace = "t" * 90
    payload = _payload(
        _span(traceId=trace, spanId="051581bf3cb55c13"),
        _span(traceId=trace, spanId="99e0f1a2b3c4d5e6"),
    )

    batch = OtlpJsonAgentTelemetryAdapter().parse(payload, platform="vercel")

    assert batch.skipped == 0
    assert len({record.origin_id for record in batch.records}) == 2


def test_identity_too_long_for_its_column_is_skipped_not_trimmed():
    trace = "t" * (MAX_ORIGIN_ID_LENGTH + 20)

    batch = OtlpJsonAgentTelemetryAdapter().parse(_payload(_span(traceId=trace)), platform="vercel")

    assert batch.records == ()
    assert batch.skip_reasons == {"oversized_identity": 1}


def test_one_oversized_span_does_not_cost_the_rest_of_the_batch():
    payload = _payload(_span(), _span(spanId="99e0f1a2b3c4d5e6", traceId="t" * 300))

    batch = OtlpJsonAgentTelemetryAdapter().parse(payload, platform="vercel")

    assert len(batch.records) == 1
    assert batch.records[0].origin_id == "5b8aa5a2d2c872e8321cf37308d69df2:051581bf3cb55c13"
    assert batch.skip_reasons == {"oversized_identity": 1}


def test_a_long_resource_identity_is_not_capped_into_a_collision():
    """``server.address`` decides the resource node. Two distinct 250-char hosts
    must stay two resources — the old 200-char read cap merged them."""
    long_host = "h" * 240
    spans = [
        _span(attributes=[_attr("gen_ai.agent.id", "invoice-bot"), _attr("server.address", long_host + "-one")]),
        _span(
            spanId="99e0f1a2b3c4d5e6",
            attributes=[_attr("gen_ai.agent.id", "invoice-bot"), _attr("server.address", long_host + "-two")],
        ),
    ]

    batch = OtlpJsonAgentTelemetryAdapter().parse(_payload(*spans), platform="vercel")

    assert len({record.resource_ref for record in batch.records}) == 2


def test_stored_attributes_are_still_bounded():
    """Dropping the read-time cap must not let an unbounded value into metadata."""
    span = _span(attributes=[*_span()["attributes"], _attr("gen_ai.request.model", "m" * 900)])

    batch = OtlpJsonAgentTelemetryAdapter().parse(_payload(span), platform="vercel")

    assert len(batch.records[0].attributes["gen_ai.request.model"]) == MAX_ATTRIBUTE_VALUE_LENGTH


def test_malformed_payload_is_rejected():
    adapter = OtlpJsonAgentTelemetryAdapter()
    for bad in ({}, {"resourceSpans": "nope"}, {"resourceSpans": ["nope"]}):
        with pytest.raises(AgentTelemetryPayloadError):
            adapter.parse(bad, platform="vercel")


def test_oversized_batch_is_rejected():
    spans = [_span(spanId=f"{index:016x}") for index in range(MAX_SPANS_PER_BATCH + 1)]

    with pytest.raises(AgentTelemetryPayloadError):
        OtlpJsonAgentTelemetryAdapter().parse(_payload(*spans), platform="vercel")


def test_agent_urn_refuses_a_ref_it_cannot_represent():
    with pytest.raises(ValueError):
        AgentUrn.build("vercel", "bad id with spaces")
    with pytest.raises(ValueError):
        AgentUrn.build("", "invoice-bot")
    assert AgentUrn.build("Vercel", "invoice-bot").value == "urn:agent:vercel:invoice-bot"
    assert AgentUrn.build("vercel", "invoice-bot").platform == "vercel"
    assert AgentUrn.build("vercel", "invoice-bot").external_ref == "invoice-bot"


def test_registry_resolves_the_otlp_adapter_and_refuses_unknown_kinds():
    provider = AgentTelemetryProvider()

    assert isinstance(provider.get("otlp_json"), OtlpJsonAgentTelemetryAdapter)
    assert "otlp_json" in provider.kinds()
    with pytest.raises(UnsupportedAgentTelemetryKindError):
        provider.get("vercel_trace_drain_v2")
