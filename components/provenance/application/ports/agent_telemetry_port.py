"""``AgentTelemetryPort`` — the seam every agent-telemetry capture mechanism plugs into.

ADR 0023 D2 splits accountability into two independent axes: **behaviour** (which
agent, which tool, which resource, when) and **capability/identity** (what it COULD
do, and as whom). This port is the *behaviour* axis, and it is deliberately shaped
to the Application Core's need — "here is an opaque payload from a capture
mechanism; give me normalized :class:`AgentActivityRecord`s" — not to OTLP, not to
the Vercel Drains API, not to the AI SDK. Rule C5.

It is the registry template's sixth use (``ScannerPort`` → ``LogSourcePort`` →
``VcsPort`` → ``DeliveryChannelPort`` → ``PostureProvider`` → here). Adding a
capture mechanism is **a new adapter + one registry line**; the ledger, the
consent model, and the REST surface do not move.

Provenance-internal, like ``LogSourcePort`` is integrations-internal: only this
context implements and consumes it, so it lives here rather than in the shared
kernel.

**How a Vercel Trace Drain plugs in later without touching the ledger.** A Trace
Drain POSTs OTLP/HTTP to any custom endpoint, which is exactly what the first
adapter already parses — so the drain is a *deployment* change (provision the
drain via Vercel's Drains REST API at this endpoint, plus a drain-token
authenticator) and not a code change to anything below this line. An AI-SDK-native
or pull-based adapter is likewise a sibling class registered by ``KIND``.

⚠ **The normalization layer is not optional.** The split-out GenAI semantic
conventions repo has no releases or tags, nothing in it is Stable, and
OpenInference (Arize) is a competing convention we will also see. Adapters
therefore consume the wire shape *defensively* and normalize; nothing downstream
may assume a stable vendor contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.provenance.domain.entities.agent_activity_entity import AgentActivityRecord


@dataclass(frozen=True)
class AgentTelemetryBatch:
    """One parsed payload: the records we could normalize, plus what we could not.

    ``skipped`` counts spans that were well-formed but not attributable to an
    agent or a resource. That is a *fail-closed* outcome, not an error: platform
    fetch spans routinely carry no agent attribute, and we would rather drop a
    span than invent an actor for it. Surfacing the count keeps our own coverage
    claim honest — every accountability statement is "of the traffic we see".
    """

    records: tuple[AgentActivityRecord, ...] = ()
    skipped: int = 0
    skip_reasons: dict = field(default_factory=dict)


class AgentTelemetryPort:
    """Interface (structural): implement ``KIND`` + ``parse`` to be an adapter.

    A plain class rather than an ABC, matching ``LogSourcePort`` — an adapter may
    subclass or merely duck-type it; the provider wires the concrete adapter by
    ``kind``.
    """

    #: Registry discriminator; matches ``AgentTelemetrySource.Kind``.
    KIND: str = ""

    def parse(self, payload: dict, *, platform: str) -> AgentTelemetryBatch:
        """Normalize one capture payload into canonical records.

        ``platform`` comes from the consented source row and becomes the middle
        segment of every ``urn:agent:`` identity, so one adapter serves many
        platforms without the payload getting to choose its own namespace.

        Implementations MUST raise
        :class:`~components.provenance.domain.errors.AgentTelemetryPayloadError`
        for a malformed or oversized payload and
        :class:`~components.provenance.domain.errors.AgentTelemetryContentRejectedError`
        when the payload carries prompt or tool-argument content — never
        strip-and-continue (see that error's docstring for why).
        """
        raise NotImplementedError
