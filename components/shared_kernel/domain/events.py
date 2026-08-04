from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base type for immutable domain facts."""

    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
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


# ── CNAPP finding spine (ADR 0004) ───────────────────────────────────
#
# The event backbone of the hub-and-spoke finding model. Scanners emit
# ``FindingObserved``; the ``findings`` context (the owner) persists and emits
# ``FindingRaised`` / ``FindingResolved``; the security-graph correlation job emits
# ``AttackPathDetected``. All fields are JSON-safe primitives so the events
# round-trip through ``CeleryEventPublisher`` — severity/status/asset-URN travel as
# their string forms (``Severity.value`` etc.), not the shared value objects. The
# rich types (``components.shared_kernel.domain.security``) are used inside a
# context's domain; the strings are the wire format.
#
# These are contracts only in Phase 1 — no component consumes them yet. They live in
# the shared kernel so emitter and subscriber never import each other (Graça's
# "Decoupling the components": the event lives in the kernel, both depend on it).


@dataclass(frozen=True, kw_only=True)
class FindingObserved(DomainEvent):
    """A scanner observed a normalized finding for an asset.

    Emitted by a scanning component; the ``findings`` context's handler persists it
    (owner-persists — a component never writes data it does not own). ``fingerprint``
    is the stable dedup key within ``(workspace_id, source)`` so a nightly re-scan
    updates ``last_seen`` on the existing finding instead of creating a duplicate.
    """

    workspace_id: UUID
    source: str  # the pillar/scanner, e.g. "cloud_posture.prowler"
    fingerprint: str  # stable dedup key within (workspace_id, source)
    asset_urn: str  # AssetUrn.value — the cross-pillar correlation key
    severity: str  # Severity.value
    title: str
    description: str = ""
    remediation: str = ""
    compliance: dict = field(default_factory=dict)  # framework tags (JSON-safe)
    attributes: dict = field(default_factory=dict)  # pillar-specific extras (JSON-safe)


@dataclass(frozen=True, kw_only=True)
class FindingRaised(DomainEvent):
    """The ``findings`` context persisted a new or re-observed open finding.

    The cross-context signal the lenses react to — agents (triage/posture), the
    workflow SOAR engine (mirrors its ``finding_raised`` / ``finding_critical``
    triggers), report, and the board (which keeps a local copy of the finding).
    ``is_new`` distinguishes a first observation from a re-observation of an already
    open finding, so consumers can avoid re-alerting on steady-state noise.
    """

    workspace_id: UUID
    finding_id: UUID
    fingerprint: str
    asset_urn: str
    severity: str  # Severity.value
    status: str  # FindingStatus.value
    source: str
    title: str
    is_new: bool
    # Vulnerability identity, when the source carries one (additive; "" otherwise).
    # SCA/CVE-shaped findings often share near-identical titles ("CVE-… in openssl"
    # across images) — outbound alerts need the id + package to stay distinguishable
    # without a cross-context read back into the findings store.
    vulnerability_id: str = ""  # e.g. CVE-2024-1234 or GHSA-… (attributes["vulnerability_id"|"cve"|"cve_id"])
    package: str = ""  # affected package name (attributes["pkg_name"|"package"|"package_name"])


@dataclass(frozen=True, kw_only=True)
class FindingResolved(DomainEvent):
    """A finding transitioned to a terminal state (resolved or suppressed).

    ``reason`` is a coarse token — e.g. ``"no_longer_observed"`` / ``"remediated"`` /
    ``"suppressed"`` — so consumers can close a board card or stop a workflow.
    """

    workspace_id: UUID
    finding_id: UUID
    fingerprint: str
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class AttackPathDetected(DomainEvent):
    """The security-graph correlation job found a toxic combination.

    A path across findings + entitlement edges + exposure that reaches a sensitive
    asset — the CNAPP crown-jewel signal. Computed by the Phase-6 background job
    (ADR 0004 §6), surfaced as a high-signal finding/board card. ``asset_urns`` is
    the node chain; ``finding_ids`` are the contributing findings, as strings so the
    lists stay JSON-safe on the wire.
    """

    workspace_id: UUID
    path_id: UUID
    severity: str  # Severity.value
    title: str
    asset_urns: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class VulnIntelRefreshed(DomainEvent):
    """The daily threat-intel feed pull landed a fresh EPSS / KEV snapshot (ADR 0013 D2).

    Emitted by ``vuln_intel.refresh_feeds`` after a new dated snapshot is persisted. The
    ``findings`` context subscribes and fans out a contextual-risk recompute per
    workspace — because a CVE can *newly* enter KEV, or its EPSS can jump, without any
    finding changing, so the materialized score must be recomputed on the feed moving,
    not only on ``FindingRaised``/``FindingResolved`` (ADR 0013 D3).

    Lives in the shared kernel because the emitter (``vuln_intel``) and the subscriber
    (``findings``) are different bounded contexts — same rationale as the finding events.
    The version fields are the snapshot stamps (empty string when that feed's pull
    failed this cycle) so a consumer/audit can see which intel triggered the rescore.
    """

    epss_score_date: str = ""  # ISO date of the EPSS snapshot, or "" if EPSS failed
    kev_catalog_version: str = ""  # KEV catalogVersion, or "" if KEV failed
