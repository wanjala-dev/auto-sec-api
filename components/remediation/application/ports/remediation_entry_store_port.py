"""Port: persist + read back RemediationEntry rows (the vetted corpus).

Every read is workspace-scoped — the tenant boundary (ADR 0012 D4) is a
mandatory argument, not an optional filter, so a caller cannot accidentally
retrieve across workspaces. ``save`` is the *only* persistence entry point, and
it is reached only from the gated use case.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry


class RemediationEntryStorePort(ABC):
    @abstractmethod
    def save(self, entry: RemediationEntry) -> RemediationEntry:
        """Insert or update; returns the persisted entity."""

    @abstractmethod
    def get(self, entry_id: UUID, *, workspace_id: UUID) -> RemediationEntry | None:
        """Load one entry scoped to its workspace (tenant isolation)."""

    @abstractmethod
    def find_by_finding_task(self, *, workspace_id: UUID, finding_task_id: str) -> RemediationEntry | None:
        """Return the (single) active entry for a finding/task in a workspace, if
        one already cleared the gate — used for idempotency (one entry per fix)."""

    @abstractmethod
    def list_for_workspace(self, workspace_id: UUID, *, limit: int = 50) -> list[RemediationEntry]:
        """The active (non-revoked) corpus for a workspace, newest-first. Never
        crosses a workspace boundary (D4)."""

    @abstractmethod
    def find_active_priors(
        self,
        *,
        workspace_id: UUID,
        finding_kind: str,
        exclude_entry_id: UUID,
        limit: int = 50,
    ) -> list[RemediationEntry]:
        """Active entries in *workspace_id* of the same *finding_kind*, excluding
        *exclude_entry_id* — the priors a newly-admitted fix's outcome propagates
        to (P5). Workspace-scoped (D4)."""

    @abstractmethod
    def filter_active_entry_ids(self, *, workspace_id, entry_ids: list[str]) -> set[str]:
        """Of *entry_ids*, return (as strings) the subset that are ACTIVE
        (non-revoked) rows in *workspace_id*. The retrieval authority check (P5):
        the soft-delete — not the fragile embedding-delete — decides retrievability,
        so retrieval drops any candidate chunk whose entry is not in this set.
        Workspace-scoped (D4); an empty input returns an empty set (no query)."""

    # ── Outcome mutations (P5) — DERIVED score only; no raw score write ──────
    # These are corpus writes, so — per ADR 0012 D1 — they live ONLY on the
    # sole-writer repository. Each recomputes ``score`` from the (bumped) counters
    # via ``RemediationRankingPolicy``; a caller can never set the rating directly.

    @abstractmethod
    def record_reuse_success(self, *, entry_id: UUID, workspace_id: UUID) -> RemediationEntry | None:
        """A same-class fix grounded on this entry merged/resolved — bump
        reuse+success and re-derive the score. Workspace-scoped; ``None`` if the
        entry is absent/revoked."""

    @abstractmethod
    def record_recurrence(self, *, entry_id: UUID, workspace_id: UUID) -> RemediationEntry | None:
        """The finding this entry fixed recurred — bump recurrence and re-derive
        the (now lower) score. Workspace-scoped; ``None`` if absent/revoked."""

    @abstractmethod
    def iter_reindex_candidate_ids(
        self, *, workspace_id: UUID | None = None, limit: int = 1000
    ) -> list[tuple[str, str]]:
        """Return ``(entry_id, workspace_id)`` string pairs for ACTIVE entries that are
        ORPHANED (never embedded — ``embedded_at IS NULL``) or rating-STALE (embedded
        before their last outcome) — the P6 re-index-sweep candidates.

        ``workspace_id=None`` spans all workspaces: this is the ONE maintenance read that
        may, because each returned pair re-embeds in ITS OWN workspace (retrieval-time D4
        is untouched). It lives on the sole-writer repository so the RemediationEntry ORM
        model import stays confined there (the D1 model-locality guard)."""

    @abstractmethod
    def mark_embedded(self, *, entry_id: UUID, workspace_id: UUID) -> None:
        """Stamp ``embedded_at = now`` after a successful (re-)embed (P6 bookkeeping).

        A retrievability marker, not corpus content or membership — so it does not
        weaken the D1 sole-writer invariant (it neither creates an entry nor sets its
        gate facts/rating). Workspace-scoped (D4): a foreign id stamps nothing. The
        ``reindex_remediation_corpus`` sweep uses the stamp to tell an embedded entry
        from an orphaned one (``embedded_at IS NULL``) or a stale one."""

    @abstractmethod
    def revoke(
        self,
        *,
        entry_id: UUID,
        workspace_id: UUID,
        revoked_by: str,
        reason: str,
    ) -> RemediationEntry | None:
        """Soft-delete (revoke) an entry so it leaves the retrievable corpus while
        its audit row survives (P5). Workspace-scoped (D4): a foreign id resolves to
        ``None`` and revokes nothing. Idempotent — revoking an already-revoked entry
        returns it unchanged."""
