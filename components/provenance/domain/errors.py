"""Provenance domain errors, on the shared taxonomy.

The agent-telemetry ingest path is internet-facing and consumes untrusted input,
so its failure modes are first-class domain concepts rather than bare
``ValueError``s: the controller maps each to a distinct HTTP status, and nothing
is silently swallowed. Each subclasses the shared kernel base whose HTTP mapping
it wants, so a caller can also catch at the taxonomy level.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    ConfigurationError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class ProvenanceError(DomainError):
    """Base for provenance-context domain errors."""


class AgentTelemetryError(ProvenanceError):
    """Base for agent-runtime telemetry ingest failures."""


class AgentTelemetrySourceUnavailableError(AgentTelemetryError, NotFoundError):
    """No ACTIVE :class:`AgentTelemetrySource` for this workspace + id.

    Fail-closed: a missing, disabled, draft, or cross-workspace source ingests
    nothing. The consent row IS the consent (the ADR 0021 D3 precedent). The
    message deliberately does not distinguish those cases — an ingest endpoint
    that reveals which source ids exist in other tenants is an enumeration oracle.
    """


class UnsupportedAgentTelemetryKindError(AgentTelemetryError, ConfigurationError):
    """No ``AgentTelemetryPort`` adapter is registered for the source's kind.

    Raised, never silently no-op'd: a consented source whose adapter is missing
    would otherwise accept batches and store nothing — the "routable without a
    tool is a silent no-op" failure mode, wearing a different hat.
    """


class AgentTelemetryPayloadError(AgentTelemetryError, ValidationError):
    """The payload is malformed, oversized, or not the shape the adapter parses."""


class AgentTelemetryContentRejectedError(AgentTelemetryPayloadError):
    """The payload carried prompt/tool-argument CONTENT.

    Metadata-only is the default posture (ADR 0023 D3) and this slice enforces it
    by **refusing the batch**, not by stripping it. The Vercel AI SDK records
    inputs and outputs *by default* — the opposite of the OTel spec's opt-in
    posture — so a silent strip would let a misconfigured customer stream prompt
    content at us indefinitely with no signal that their exporter is wrong. A loud
    refusal naming the offending attribute keys pushes the fix to where it belongs
    (``recordInputs: false`` at the source), and keeps content out of our process
    entirely rather than out of our database only.

    The trade is deliberate: a fire-and-forget drain loses the refused batch. We
    would rather drop telemetry than quietly accumulate a customer's end-users'
    prompt data.
    """

    def __init__(self, keys: tuple[str, ...]):
        self.keys = keys
        super().__init__(
            "Payload carries prompt/tool-argument content; this endpoint is metadata-only. "
            f"Disable content recording at the exporter. Offending attribute keys: {', '.join(keys)}"
        )
