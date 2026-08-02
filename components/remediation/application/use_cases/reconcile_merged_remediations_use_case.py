"""ReconcileMergedRemediationsUseCase — turn a MERGED draft PR into a resolved
finding and (gate permitting) a corpus entry (ADR 0012 Phase 4a).

This is the reconciler that finally makes the P3 entry-gate populate the corpus.
It closes P3's two honest residuals:

- **"applied" was an operator claim.** Here it is the host's un-forgeable
  ``merged`` boolean, read back via ``PullRequestMergeCheckPort`` (→ the
  integrations ``VcsPort``). ``pr_applied=True`` is supplied ONLY for a verified
  merge — never a blind flag.
- **findings never resolved.** When a PR is verified merged, this use case marks
  the finding ``resolved`` via ``FindingResolutionPort`` — the clean transition
  the board previously lacked — so the gate's third leg can become true.

It is an *authorized caller* of the gate, not a second writer: it supplies
verified facts (merged via the API, resolved via the transition it just made) and
lets ``RecordRemediationEntryUseCase`` — the SOLE corpus writer — decide. The gate
independently re-checks sign-off + resolved + applied. If sign-off is not
approved, the finding still resolves but the gate REFUSES the entry (no corpus
write) — which is correct (ADR 0012 D1).

Idempotent: a finding already resolved / already holding a RemediationEntry is a
no-op (the resolution adapter's already-resolved guard + the gate's
``find_by_finding_task`` short-circuit). Safe to run every cycle.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from components.remediation.application.ports.finding_remediation_facts_port import (
    FindingRemediationFactsPort,
)
from components.remediation.application.ports.finding_resolution_port import (
    FindingResolutionPort,
)
from components.remediation.application.ports.open_draft_pr_findings_port import (
    OpenDraftPrFindingsPort,
)
from components.remediation.application.ports.pull_request_merge_check_port import (
    PullRequestMergeCheckPort,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry

logger = logging.getLogger(__name__)

# Stable sign-off artifact identity for a remediation. The gate re-checks approval
# for (type, id); today the fork registers no sign_off adapter, so the gate refuses
# the corpus write while the finding still resolves — the correct P4a behaviour.
_SIGN_OFF_ARTIFACT_TYPE = "remediation"

# The captured fix's raw content must be non-empty (RemediationEntry invariant);
# when the finding carries no suggested_fix text we still resolve it but skip the
# corpus offer rather than record an empty entry.
_MIN_FIX_LEN = 1

# What ``capture_remediation_if_gated`` accepts — injected so tests wire a fake and
# production uses the real gated facade.
CaptureFn = Callable[..., RemediationEntry | None]


@dataclass(frozen=True)
class ReconcileResult:
    scanned: int
    merged: int
    resolved: int
    captured: int


class ReconcileMergedRemediationsUseCase:
    def __init__(
        self,
        *,
        candidates: OpenDraftPrFindingsPort,
        merge_check: PullRequestMergeCheckPort,
        finding_facts: FindingRemediationFactsPort,
        resolution: FindingResolutionPort,
        capture: CaptureFn,
        chunk_size: int = 500,
    ) -> None:
        self._candidates = candidates
        self._merge_check = merge_check
        self._finding_facts = finding_facts
        self._resolution = resolution
        self._capture = capture
        self._chunk_size = chunk_size

    def execute(self) -> ReconcileResult:
        scanned = merged = resolved = captured = 0

        for candidate in self._candidates.iter_open_draft_pr_findings(chunk_size=self._chunk_size):
            scanned += 1
            try:
                was_merged, was_captured = self._reconcile_one(candidate)
            except Exception:
                # One bad finding must never abort the whole sweep (bulk per-item
                # loop — the sanctioned broad-catch pattern). Traceback preserved.
                logger.exception(
                    "remediation_reconcile_item_failed workspace_id=%s finding_task_id=%s",
                    candidate.workspace_id,
                    candidate.finding_task_id,
                )
                continue
            if was_merged:
                merged += 1
                resolved += 1
            captured += was_captured

        result = ReconcileResult(scanned=scanned, merged=merged, resolved=resolved, captured=captured)
        logger.info(
            "remediation_reconcile_completed scanned=%s merged=%s resolved=%s captured=%s",
            result.scanned,
            result.merged,
            result.resolved,
            result.captured,
        )
        return result

    def _reconcile_one(self, candidate) -> tuple[bool, int]:
        """Reconcile a single candidate. Returns ``(was_merged, captured)`` where
        ``was_merged`` is True iff the PR was verified merged (and the finding
        therefore resolved), and ``captured`` is 1 iff the gate additionally
        admitted a corpus entry, else 0."""
        status = self._merge_check.check_merged(
            workspace_id=candidate.workspace_id,
            repo=candidate.repo,
            pr_ref=candidate.pr_url,
        )
        if not (status.checked and status.merged):
            # Not merged, or could not verify → leave for the next cycle.
            return False, 0

        # Verified merged. Transition the finding to resolved (idempotent).
        self._resolution.mark_resolved(
            workspace_id=candidate.workspace_id,
            finding_task_id=candidate.finding_task_id,
            reason=f"PR merged {status.pr_url}".strip(),
        )

        # Re-read the finding facts (now resolved) to build the capture offer.
        facts = self._finding_facts.get_facts(
            workspace_id=candidate.workspace_id,
            finding_task_id=candidate.finding_task_id,
        )
        if not facts.exists or not facts.draft_pr_url:
            return True, 0
        if len(facts.fix_code) < _MIN_FIX_LEN:
            # Nothing groundable to record — resolve only, no empty corpus entry.
            logger.info(
                "remediation_reconcile_no_fix_code workspace_id=%s finding_task_id=%s",
                candidate.workspace_id,
                candidate.finding_task_id,
            )
            return True, 0

        # Offer the candidate to the gate with VERIFIED applied=True. The gate
        # re-checks sign-off + resolved + applied and either admits or refuses.
        entry = self._capture(
            workspace_id=UUID(candidate.workspace_id),
            finding_task_id=candidate.finding_task_id,
            sign_off_artifact_type=_SIGN_OFF_ARTIFACT_TYPE,
            sign_off_artifact_id=candidate.finding_task_id,
            applied_pr_url=facts.draft_pr_url,
            code=facts.fix_code,
            language="",
            title=facts.title,
            summary=facts.summary,
            pr_applied=True,
        )
        return True, (1 if entry is not None else 0)
