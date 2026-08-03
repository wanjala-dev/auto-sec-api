"""PropagateRemediationOutcomesUseCase — turn a NEW admission into outcome signals
on the priors it relates to (ADR 0012 P5, "did this fix hold?").

Runs at exactly one moment: when the entry-gate ADMITS a brand-new entry (never on
an idempotent re-run — see ``RecordRemediationEntryUseCase.on_admit``). At that
moment a fix of some ``finding_kind`` in a workspace demonstrably merged + resolved,
which tells us something about the OTHER vetted priors of the same class:

- **Recurrence (negative).** A prior whose finding *fingerprint* matches the one we
  just re-fixed means the earlier fix did NOT hold — the same finding came back and
  needed fixing again. That prior gets a recurrence signal (its score drops), and —
  per the ADR's D1 revocation residual — a fix that keeps recurring is a candidate
  for governance revocation.
- **Reuse + success (positive).** A same-``finding_kind`` prior with a *different*
  fingerprint is a fix of the same class that grounded this new, now-successful
  remediation; it earns a reuse+success signal (its score rises).

This is deliberately computed at the capture seam from facts already in the corpus
(same workspace, same kind, matching/other fingerprint) — no new provenance
plumbing — so it works for BOTH the reconciler and any operator capture path. Each
mutated prior is re-embedded (its chunk carries the score retrieval ranks on), so a
score change reaches retrieval immediately; re-embed is dispatched through an
injected callable, keeping this use case framework-free.

Every write goes through the store port's outcome mutations (which the sole-writer
repository implements) — the score is DERIVED, never set from input (D1: a rating
can't be forged).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from components.remediation.application.ports.remediation_entry_store_port import (
    RemediationEntryStorePort,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutcomePropagationResult:
    reuse_success: int = 0
    recurrence: int = 0


class PropagateRemediationOutcomesUseCase:
    def __init__(
        self,
        *,
        store: RemediationEntryStorePort,
        reembed: Callable[[UUID, UUID], None] | None = None,
    ) -> None:
        self._store = store
        # reembed: (entry_id, workspace_id) -> None. Re-index a prior whose score
        # changed so retrieval ranks it on the new rating. Optional (tests may omit).
        self._reembed = reembed

    def execute(self, entry: RemediationEntry) -> OutcomePropagationResult:
        priors = self._store.find_active_priors(
            workspace_id=entry.workspace_id,
            finding_kind=entry.finding_kind,
            exclude_entry_id=entry.id,
        )
        reuse_success = recurrence = 0
        fp = (entry.finding_fingerprint or "").strip()

        for prior in priors:
            if fp and (prior.finding_fingerprint or "").strip() == fp:
                # The exact finding recurred — the prior fix did not hold.
                updated = self._store.record_recurrence(entry_id=prior.id, workspace_id=prior.workspace_id)
                if updated is not None:
                    recurrence += 1
                    self._dispatch_reembed(prior)
            else:
                # A same-class prior grounded this new, successful fix.
                updated = self._store.record_reuse_success(entry_id=prior.id, workspace_id=prior.workspace_id)
                if updated is not None:
                    reuse_success += 1
                    self._dispatch_reembed(prior)

        logger.info(
            "remediation_outcomes_propagated entry_id=%s workspace_id=%s finding_kind=%s "
            "reuse_success=%s recurrence=%s priors=%s",
            entry.id,
            entry.workspace_id,
            entry.finding_kind,
            reuse_success,
            recurrence,
            len(priors),
        )
        return OutcomePropagationResult(reuse_success=reuse_success, recurrence=recurrence)

    def _dispatch_reembed(self, prior: RemediationEntry) -> None:
        if self._reembed is None:
            return
        try:
            self._reembed(prior.id, prior.workspace_id)
        except Exception:
            # Re-embed is an enhancement (the score is already persisted); a dispatch
            # failure must never fail outcome propagation.
            logger.exception(
                "remediation_outcome_reembed_dispatch_failed entry_id=%s workspace_id=%s",
                prior.id,
                prior.workspace_id,
            )
