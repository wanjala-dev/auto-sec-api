from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base type for immutable domain facts."""

    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class TaskAcceptedFromBoard(DomainEvent):
    """A Kanban task was moved into an "Accepted" column.

    Phase 4 of the Agents-as-Teammates migration
    (``docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md``). When a user
    drags an AI-finding task into "Accepted" on the agent team board,
    the ``ai-findings-accepted`` workflow's ``publish_event`` node
    fires this event. Phase 5 specialist agents subscribe to it to
    take follow-up action (e.g. budget specialist queues a budget
    review, sponsorship specialist drafts a check-in message).

    The event lives in the shared kernel because handlers across many
    contexts will subscribe to it — placing it in any single context's
    ``domain/events/`` would force every subscriber to import that
    context's namespace.
    """

    workspace_id: UUID
    task_id: UUID
    source_type: str
    accepted_at: datetime
    user_id: UUID | None = None
    previous_column_id: UUID | None = None
    new_column_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class SignOffDecisionRecorded(DomainEvent):
    """A human reviewer made a sign-off decision on an AI-generated artifact.

    Phase 6c of the Verification-Assisted Sign-Off Spine (SEE-190). Emitted by
    ``SignOffQueueService`` after a decision (approve / request-changes /
    reject) is delegated to the artifact's context and audited. The
    feedback→eval bridge (a handler in ``components.agents.application.handlers``)
    subscribes and turns qualifying decisions into labeled eval examples for the
    content generators.

    Lives in the shared kernel because the emitter (``sign_off``) and the
    subscriber (``agents`` eval) are different bounded contexts — same rationale
    as ``TaskAcceptedFromBoard``.

    Fields are JSON-safe so the event round-trips through ``CeleryEventPublisher``
    (``reason_codes`` is a ``list``, never a tuple, so it deserialises
    unchanged; ids are plain strings, not UUIDs, matching how the queue service
    already handles them).

    ``decision`` is the review token the queue used: ``"approved"`` /
    ``"changes_requested"`` / ``"rejected"``. ``risk_band`` is the band at
    decision time: ``"green"`` / ``"amber"`` / ``"red"``.
    """

    artifact_type: str
    artifact_id: str
    decision: str
    risk_band: str
    reason_codes: list[str] = field(default_factory=list)
    note: str = ""
    actor_id: str | None = None
    workspace_id: str | None = None
