"""``AgentActivityRecord`` — one normalized, metadata-only agent action.

The canonical shape every ``AgentTelemetryPort`` adapter produces, and the only
shape the ledger writes from. Capture mechanisms differ wildly (an OTLP push, a
Vercel Trace Drain, an SDK exporter, a future pull adapter); this record is what
they all agree on, so the ledger never learns where a span came from.

It maps 1:1 onto the existing provenance graph (ADR 0023 D1 — no new store):

* ``agent_urn``   → :class:`ProvenanceActor` (``actor_type=ai_agent``,
  ``source_system=agent_runtime``, ``external_ref=<the urn>``)
* ``resource_ref``→ :class:`ProvenanceResource` (the thing touched)
* the record      → :class:`ProvenanceEvent` (``origin=agent_runtime``,
  ``origin_id=<trace_id>:<span_id>``)

``AccessGrant`` — the *potential* half of the model — is deliberately **not**
written here. This is the DID axis only; the CAN axis reads the customer's grant
surface and is a separate phase (ADR 0023 P1).

**Metadata-only by construction.** ``attributes`` is a small, capped bag of
non-content dimensions (host, status, duration, model name). Prompt bodies and
tool arguments never reach this type — the adapter refuses the batch upstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ProvenanceEvent.action is CharField(128); ProvenanceResource.external_ref is 512.
MAX_ACTION_LENGTH = 128
MAX_RESOURCE_REF_LENGTH = 512


@dataclass(frozen=True)
class AgentActivityRecord:
    """One agent action, as reported by the customer's own runtime.

    ``agent_urn`` is an *asserted* identity — self-reported telemetry is not
    trustworthy evidence about the agent that reported it. Callers must treat
    this as attributable, never as proven (ADR 0023 §2.4 / D6: the word
    "provable" is not licensed until tamper-evidence lands).
    """

    agent_urn: str
    resource_ref: str
    resource_type: str
    action: str
    occurred_at: datetime
    trace_id: str
    span_id: str
    outcome: str = "unknown"
    tool_name: str = ""
    attributes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.agent_urn:
            raise ValueError("AgentActivityRecord requires an agent_urn")
        if not self.resource_ref:
            raise ValueError("AgentActivityRecord requires a resource_ref")
        if not self.action:
            raise ValueError("AgentActivityRecord requires an action")
        if not self.span_id:
            raise ValueError("AgentActivityRecord requires a span_id")
        if self.occurred_at.tzinfo is None:
            raise ValueError("AgentActivityRecord.occurred_at must be timezone-aware")
        object.__setattr__(self, "action", self.action[:MAX_ACTION_LENGTH])
        object.__setattr__(self, "resource_ref", self.resource_ref[:MAX_RESOURCE_REF_LENGTH])

    @property
    def origin_id(self) -> str:
        """Idempotency key within ``(workspace, origin)``.

        A W3C trace id is 32 hex chars and a span id 16, so this fits
        ``ProvenanceEvent.origin_id``'s 64-char column with room to spare. A span
        id alone is only unique within its trace, which is why both are carried.
        """
        return f"{self.trace_id}:{self.span_id}"[:64]
