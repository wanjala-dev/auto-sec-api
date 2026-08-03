"""RemediationEntry — a vetted, gated fix in the Remediation Memory corpus.

A frozen domain entity (aggregate-light, per the architecture skill). Its
existence is a *fact*: this fix cleared the D1 entry-gate (sign-off approved,
PR applied, finding resolved) and is therefore admissible into the retrievable,
per-workspace library. The entity does **not** decide its own admission — the
``EntryGatePolicy`` domain service + the sole gated use case do that; by the time
an entity is constructed the gate has already passed.

Invariants (ADR 0012 D3/D4): ``code`` is RAW fix text (never rendered HTML),
``workspace_id`` is always present (the tenant boundary), and the provenance
link (``finding_task_id``) ties the entry to the board fact it *is* — not a copy.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class RemediationEntry:
    id: UUID
    workspace_id: UUID
    # Retrieval keys — what class of finding this fix is for.
    finding_kind: str
    source_type: str
    tags: tuple[str, ...]
    # The fix — RAW code + language (D3: never store rendered HTML).
    language: str
    code: str
    title: str
    summary: str
    # Provenance link — the same fact as the board event, linked not duplicated.
    finding_task_id: str
    finding_fingerprint: str
    provenance_event_ref: str
    # Evidence the gate passed (D1).
    applied_pr_url: str
    approved_by: str
    resolved_at: datetime
    # Outcome / ranking (ADR 0012 P5). ``score`` is DERIVED from the counters by
    # ``RemediationRankingPolicy.derive_score`` — never caller-set — so a rating
    # can't be forged to game retrieval. The counters record the "did this fix
    # hold?" loop: reuse/success raise the score, recurrence lowers it.
    reuse_count: int = 0
    success_count: int = 0
    recurrence_count: int = 0
    last_outcome_at: datetime | None = None
    score: int = 0
    # Retrievability bookkeeping (P6): when this entry was last successfully embedded
    # into the corpus. ``None`` ⇒ never embedded (a re-index-sweep candidate).
    embedded_at: datetime | None = None
    created_at: datetime | None = None
    is_deleted: bool = False

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("RemediationEntry.workspace_id is required (D4: tenant boundary)")
        if not self.finding_kind:
            raise ValueError("RemediationEntry.finding_kind is required")
        if not self.code:
            raise ValueError("RemediationEntry.code is required (the raw fix)")
        if not self.applied_pr_url:
            raise ValueError("RemediationEntry.applied_pr_url is required (D1: PR applied)")
        if not self.approved_by:
            raise ValueError("RemediationEntry.approved_by is required (D1: sign-off approved)")
        if not self.finding_task_id:
            raise ValueError("RemediationEntry.finding_task_id is required (provenance link)")

    def revoked(self) -> RemediationEntry:
        """Pull this entry from the retrievable corpus (P5 revocation residual —
        e.g. its finding reopened). Soft-delete: the audit row survives."""
        return replace(self, is_deleted=True)
