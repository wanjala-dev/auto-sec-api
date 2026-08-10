"""OTLP/HTTP JSON → :class:`AgentActivityRecord` (the first ``AgentTelemetryPort`` adapter).

**Why this shape first.** It is the lowest common denominator: it depends on
neither the customer's Vercel plan tier nor their AI SDK major version, a plain
script can POST it today, and a Vercel Trace Drain emits precisely this over
OTLP/HTTP — so wiring the drain later is a provisioning step plus a drain-token
authenticator, never a second ingest pipeline and never a change to the ledger.

**Defensive by design.** The split-out GenAI semantic-conventions repo has no
releases or tags, nothing in it is Stable, and OpenInference is a competing
convention we will also meet. So this adapter reads a small set of attributes it
recognizes, tolerates everything else, and normalizes — it does not validate
against a schema it cannot pin.

**Metadata-only, enforced by refusal.** ``_CONTENT_ATTRIBUTE_PREFIXES`` covers both
the OTel GenAI content attributes and the Vercel AI SDK's own ``ai.*`` content
attributes (which the SDK records **by default** — the opposite of the spec's
opt-in posture). One match anywhere in the batch refuses the whole batch.

**Untrusted input.** Everything below treats the payload as attacker-authored:
bounded span count, bounded stored strings, no unbounded recursion, no attribute
value ever interpolated into a log line.

**The length cap is a STORAGE bound, not a parsing bound.**
:data:`MAX_ATTRIBUTE_VALUE_LENGTH` is applied in :func:`_kept_attributes`, where
we decide what to persist — deliberately *not* when flattening, because the same
flattened map also supplies the span's IDENTITY (agent ref, resource ref, trace
and span ids). Capping an identity while reading it is the truncation bug this
adapter must not have: two distinct endpoints sharing a 200-char prefix would
become one resource node. Identities are read whole and then refused if they do
not fit their column — a span we cannot key correctly is skipped and counted,
never quietly merged into another one. (Nothing new is held in memory by reading
whole: these are slices of an already-parsed request body, itself bounded by
``DATA_UPLOAD_MAX_MEMORY_SIZE``.)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from components.provenance.application.ports.agent_telemetry_port import (
    AgentTelemetryBatch,
    AgentTelemetryPort,
)
from components.provenance.domain.entities.agent_activity_entity import AgentActivityRecord
from components.provenance.domain.errors import (
    AgentTelemetryContentRejectedError,
    AgentTelemetryPayloadError,
)
from components.provenance.domain.value_objects.agent_urn import AgentUrn

logger = logging.getLogger(__name__)

# Bounds. A drain can retry, so refusing an oversized batch is safe; accepting an
# unbounded one is not.
MAX_SPANS_PER_BATCH = 1000
# Applied to what we STORE (metadata attributes, tool name) — never to a value
# that decides an identity. See the module docstring.
MAX_ATTRIBUTE_VALUE_LENGTH = 200
MAX_STORED_ATTRIBUTES = 12
# Longest OTLP key we will even look at. Keys are convention names, not customer
# data, so a bound here is pure defence against a pathological payload.
MAX_ATTRIBUTE_KEY_LENGTH = 200

# Attribute keys (prefix-matched) that carry prompt or tool-argument CONTENT.
# Presence of any of these refuses the batch — see AgentTelemetryContentRejectedError.
_CONTENT_ATTRIBUTE_PREFIXES = (
    # OTel GenAI semantic conventions (Opt-In in the spec).
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.prompt",
    "gen_ai.completion",
    "gen_ai.tool.call.arguments",
    "gen_ai.tool.call.result",
    "gen_ai.content",
    "gen_ai.system_instructions",
    # Vercel AI SDK's own attributes — recorded BY DEFAULT unless the customer
    # sets recordInputs/recordOutputs false. This is the realistic leak path.
    "ai.prompt",
    "ai.response.text",
    "ai.response.object",
    "ai.response.toolCalls",
    "ai.toolCall.args",
    "ai.toolCall.result",
    # OpenInference (Arize) — the competing convention we will also see.
    "input.value",
    "output.value",
    "llm.input_messages",
    "llm.output_messages",
    "llm.prompts",
)

# Non-content dimensions worth keeping on ProvenanceEvent.metadata.
_KEPT_ATTRIBUTE_KEYS = (
    "gen_ai.system",
    "gen_ai.request.model",
    "gen_ai.response.model",
    "gen_ai.operation.name",
    "gen_ai.tool.name",
    "gen_ai.tool.call.id",
    "server.address",
    "server.port",
    "http.request.method",
    "http.response.status_code",
    "url.scheme",
)

_AGENT_ATTRIBUTE_KEYS = ("gen_ai.agent.id", "gen_ai.agent.name", "service.name")
_RESOURCE_ATTRIBUTE_KEYS = ("server.address", "db.system", "messaging.system")

_STATUS_CODE_TO_OUTCOME = {0: "unknown", 1: "ok", 2: "error"}
_STATUS_NAME_TO_OUTCOME = {
    "STATUS_CODE_UNSET": "unknown",
    "STATUS_CODE_OK": "ok",
    "STATUS_CODE_ERROR": "error",
}


class OtlpJsonAgentTelemetryAdapter(AgentTelemetryPort):
    KIND = "otlp_json"

    def parse(self, payload: dict, *, platform: str) -> AgentTelemetryBatch:
        if not isinstance(payload, dict):
            raise AgentTelemetryPayloadError("Payload must be a JSON object.")
        resource_spans = payload.get("resourceSpans")
        if not isinstance(resource_spans, list):
            raise AgentTelemetryPayloadError("Payload must carry an OTLP 'resourceSpans' array.")

        records: list[AgentActivityRecord] = []
        skip_reasons: dict[str, int] = {}
        skipped = 0
        seen_spans = 0

        for resource_span in resource_spans:
            if not isinstance(resource_span, dict):
                raise AgentTelemetryPayloadError("Each resourceSpans entry must be an object.")
            resource_attrs = _attributes_of(resource_span.get("resource") or {})
            _refuse_content(resource_attrs)

            for scope_span in resource_span.get("scopeSpans") or []:
                if not isinstance(scope_span, dict):
                    raise AgentTelemetryPayloadError("Each scopeSpans entry must be an object.")
                for span in scope_span.get("spans") or []:
                    seen_spans += 1
                    if seen_spans > MAX_SPANS_PER_BATCH:
                        raise AgentTelemetryPayloadError(
                            f"Batch exceeds the {MAX_SPANS_PER_BATCH}-span cap; split it or enable drain sampling."
                        )
                    if not isinstance(span, dict):
                        raise AgentTelemetryPayloadError("Each span must be an object.")
                    record, reason = self._span_to_record(span, resource_attrs, platform=platform)
                    if record is None:
                        skipped += 1
                        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                        continue
                    records.append(record)

        return AgentTelemetryBatch(records=tuple(records), skipped=skipped, skip_reasons=skip_reasons)

    def _span_to_record(self, span: dict, resource_attrs: dict, *, platform: str):
        span_attrs = _attributes_of(span)
        _refuse_content(span_attrs)
        # A span's log-style events are the other place content hides.
        for event in span.get("events") or []:
            if isinstance(event, dict):
                _refuse_content(_attributes_of(event))

        merged = {**resource_attrs, **span_attrs}

        agent_ref = _first_present(merged, _AGENT_ATTRIBUTE_KEYS)
        if not agent_ref:
            # Fail closed: never invent an actor for an unattributable span.
            return None, "no_agent_identity"
        try:
            agent_urn = AgentUrn.build(platform, agent_ref)
        except ValueError:
            return None, "unusable_agent_identity"

        tool_name = merged.get("gen_ai.tool.name", "")
        resource_ref = _first_present(merged, _RESOURCE_ATTRIBUTE_KEYS)
        resource_type = "network_endpoint"
        if not resource_ref and tool_name:
            resource_ref, resource_type = f"tool:{tool_name}", "agent_tool"
        if not resource_ref:
            return None, "no_resource_identity"

        occurred_at = _nanos_to_datetime(span.get("startTimeUnixNano"))
        if occurred_at is None:
            return None, "no_timestamp"

        span_id = _text(span.get("spanId"))
        if not span_id:
            return None, "no_span_id"

        action = _text(merged.get("gen_ai.operation.name") or span.get("name") or "span")

        try:
            record = AgentActivityRecord(
                agent_urn=agent_urn.value,
                resource_ref=resource_ref,
                resource_type=resource_type,
                action=action,
                occurred_at=occurred_at,
                trace_id=_text(span.get("traceId")),
                span_id=span_id,
                outcome=_outcome_of(span.get("status")),
                tool_name=_bounded(tool_name),
                attributes=_kept_attributes(merged),
            )
        except ValueError:
            # An identity that does not fit its column. Skipping loses ONE span
            # and says so in the response's skip_reasons; truncating it would
            # have merged this span into another one, silently and permanently.
            # The message carries customer data, so it is not logged here — the
            # counted reason is the signal.
            return None, "oversized_identity"

        return record, ""


def _attributes_of(carrier: dict) -> dict[str, str]:
    """Flatten OTLP's ``[{key, value: {stringValue|intValue|…}}]`` into a plain map.

    Only scalars are read. A nested ``kvlistValue``/``arrayValue`` is recorded as a
    marker rather than walked — it is the shape content arrives in, so refusing to
    descend keeps this bounded AND keeps content out.
    """
    out: dict[str, str] = {}
    for item in carrier.get("attributes") or []:
        if not isinstance(item, dict):
            continue
        key = _text(item.get("key"))[:MAX_ATTRIBUTE_KEY_LENGTH]
        if not key:
            continue
        value = item.get("value")
        out[key] = _scalar_of(value)
    return out


def _scalar_of(value) -> str:
    if not isinstance(value, dict):
        return _text(value)
    for field_name in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if field_name in value:
            return _text(value[field_name])
    if "arrayValue" in value or "kvlistValue" in value or "bytesValue" in value:
        return "<structured>"
    return ""


def _text(value) -> str:
    """Normalize to a stripped string WITHOUT truncating.

    Used for every value that may end up deciding an identity. Length is judged
    later, by the field's own limit, and refused rather than trimmed.
    """
    if value is None:
        return ""
    return str(value).strip()


def _bounded(value) -> str:
    """:func:`_text` plus the storage cap. Only for values we persist as metadata."""
    return _text(value)[:MAX_ATTRIBUTE_VALUE_LENGTH]


def _first_present(attrs: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = attrs.get(key)
        if value:
            return value
    return ""


def _refuse_content(attrs: dict[str, str]) -> None:
    offenders = tuple(sorted(key for key in attrs if key.startswith(_CONTENT_ATTRIBUTE_PREFIXES)))
    if offenders:
        # The KEYS are safe to surface (they are convention names, not customer
        # data); the VALUES never leave this function.
        raise AgentTelemetryContentRejectedError(offenders)


def _kept_attributes(attrs: dict[str, str]) -> dict[str, str]:
    """Select the non-content dimensions worth persisting, and bound them.

    This is where :data:`MAX_ATTRIBUTE_VALUE_LENGTH` belongs: these values are
    stored, compared by nobody, and identify nothing.
    """
    kept = {key: attrs[key][:MAX_ATTRIBUTE_VALUE_LENGTH] for key in _KEPT_ATTRIBUTE_KEYS if attrs.get(key)}
    return dict(list(kept.items())[:MAX_STORED_ATTRIBUTES])


def _outcome_of(status) -> str:
    if not isinstance(status, dict):
        return "unknown"
    code = status.get("code")
    if isinstance(code, bool):
        return "unknown"
    if isinstance(code, int):
        return _STATUS_CODE_TO_OUTCOME.get(code, "unknown")
    return _STATUS_NAME_TO_OUTCOME.get(str(code).upper(), "unknown")


def _nanos_to_datetime(value) -> datetime | None:
    try:
        nanos = int(value)
    except (TypeError, ValueError):
        return None
    if nanos <= 0:
        return None
    try:
        return datetime.fromtimestamp(nanos / 1_000_000_000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
