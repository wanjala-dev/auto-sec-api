"""Input DTO for the agent-telemetry ingest endpoint.

Treats the body as untrusted: the ONLY structural guarantee it establishes is
"this is a JSON object of a bounded declared size". Everything semantic is the
adapter's job, because the adapter is the thing that knows the wire convention.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Declared-size ceiling. Django's DATA_UPLOAD_MAX_MEMORY_SIZE (10 MiB) is the
#: outer backstop; this is the endpoint's own, much tighter, contract. A drain
#: with per-drain sampling stays far under it, and a refusal is retryable.
MAX_PAYLOAD_BYTES = 1_048_576


class AgentTelemetryRequestError(ValueError):
    """Malformed request envelope (not a payload-semantics problem)."""


class PayloadTooLargeError(AgentTelemetryRequestError):
    """Declared body size exceeds :data:`MAX_PAYLOAD_BYTES` — mapped to HTTP 413."""


@dataclass(frozen=True)
class AgentTelemetryIngestRequest:
    payload: dict

    @classmethod
    def from_request(cls, request) -> AgentTelemetryIngestRequest:
        declared = request.META.get("CONTENT_LENGTH") or 0
        try:
            declared_bytes = int(declared)
        except (TypeError, ValueError):
            declared_bytes = 0
        if declared_bytes > MAX_PAYLOAD_BYTES:
            raise PayloadTooLargeError(
                f"Body exceeds the {MAX_PAYLOAD_BYTES}-byte ingest cap; split the batch or sample the drain."
            )

        data = request.data
        if not isinstance(data, dict):
            raise AgentTelemetryRequestError("Body must be a JSON object.")
        return cls(payload=data)
