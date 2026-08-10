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

**Identity fields raise; descriptive fields truncate.** That split is the whole
point of the length rules below, so keep it when adding a field:

* An *identity* field decides WHICH row this is — ``origin_id`` (the idempotency
  key), ``agent_urn`` (the actor), ``resource_ref`` (the resource). Each backs a
  ``UniqueConstraint``, so truncating one does not lose a suffix: it **merges two
  genuinely distinct things into one row**. Two agent actions collapse into one
  provenance event and every attribution statement built on it is false — a
  silent wrong answer, which is worse than a dropped span. These raise.
* A *descriptive* field (``action``, display names) only labels the row. A long
  value loses a suffix and nothing merges, so these truncate.

Raising here is what makes the rule enforceable on both backends: Postgres
rejects an over-length insert loudly (``value too long for type character
varying(64)``) but SQLite — our test settings — enforces no VARCHAR length at
all and stores the oversized value. A guard that lived only in the column would
therefore behave differently in tests than in production. This one does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Descriptive — ProvenanceEvent.action is CharField(128). Truncation loses a
# suffix, never an identity, so it is allowed (see the module docstring).
MAX_ACTION_LENGTH = 128

# Identity — the columns these land in. Over-length RAISES; never truncate.
# ProvenanceEvent.origin_id is CharField(128): W3C trace context needs 49
# (32 + ":" + 16), AWS X-Ray 52, and a runtime that keys spans with UUIDs needs
# 73 — which the original 64-char column could not hold.
MAX_ORIGIN_ID_LENGTH = 128
# ProvenanceResource.external_ref is CharField(512).
MAX_RESOURCE_REF_LENGTH = 512
# ProvenanceActor.external_ref is CharField(255); mirrors AgentUrn.MAX_URN_LENGTH.
MAX_AGENT_URN_LENGTH = 255


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

        # Identity fields — refuse, never truncate (see the module docstring).
        _refuse_oversized("agent_urn", self.agent_urn, MAX_AGENT_URN_LENGTH)
        _refuse_oversized("resource_ref", self.resource_ref, MAX_RESOURCE_REF_LENGTH)
        _refuse_oversized("origin_id", self._origin_id, MAX_ORIGIN_ID_LENGTH)

        # Descriptive field — a lost suffix labels the row worse; it never
        # merges two rows.
        object.__setattr__(self, "action", self.action[:MAX_ACTION_LENGTH])

    @property
    def _origin_id(self) -> str:
        return f"{self.trace_id}:{self.span_id}"

    @property
    def origin_id(self) -> str:
        """Idempotency key within ``(workspace, origin)``.

        A span id alone is only unique within its trace, which is why both are
        carried. Length is validated at construction, so this is never truncated:
        a truncated idempotency key silently merges two distinct agent actions
        into one provenance event.
        """
        return self._origin_id


def _refuse_oversized(field_name: str, value: str, limit: int) -> None:
    if len(value) > limit:
        # The value is customer-controlled, so surface only its length and a short
        # head — never the whole string, which ends up in logs and error trackers.
        raise ValueError(
            f"AgentActivityRecord.{field_name} is {len(value)} chars, over the {limit}-char limit "
            f"(starts {value[:24]!r}). Identity fields are refused rather than truncated: a truncated "
            f"identity is a WRONG identity, not a shorter one."
        )
