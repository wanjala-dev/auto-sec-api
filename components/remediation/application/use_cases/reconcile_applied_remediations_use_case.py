"""ReconcileAppliedRemediationsUseCase — turn *merged* remediation PRs into real
resolved findings + gated corpus entries (ADR 0012 P4a).

This is the plumbing ADR 0012 named as the "P4 gap" (see
``remediation_capture_handler``): until now "applied (merged)" could not be
*observed*, so the entry-gate depended on an explicit operator confirmation. This
use case closes that — it walks the findings that carry an OPEN remediation draft
PR, asks the VCS host (through the integrations application surface) whether the PR
actually **merged**, and only for the merged ones:

  a. resolves the finding through the **project** application surface (the owner of
     the board Task — this context never writes that Task itself: architecture skill
     C2/C3), then
  b. offers the fix to the **remediation** entry-gate (the gated capture), which
     re-checks sign-off-approved + PR-applied + finding-resolved and either admits
     the entry or refuses (writing nothing).

Framework-free: every cross-context reach is an injected callable resolved by the
composition root to the OWNING context's application surface — no ORM, no VCS SDK,
no other-context infrastructure import here. Idempotent by construction: an
already-resolved finding short-circuits resolution to a no-op, and the entry-gate
is itself idempotent (one entry per fix), so a re-run captures nothing new. An
unmerged PR resolves nothing and captures nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemediationCandidate:
    """A finding carrying an open remediation draft PR — a merge-check candidate.

    Assembled by the driving task from a persistence read of the board (a sanctioned
    read of ``project`` persistence, the same pattern ``BoardFindingFactsRepository``
    uses); the use case stays free of any ORM."""

    workspace_id: UUID
    finding_task_id: str
    draft_pr_url: str
    # What the gated capture needs to build its command (all read off the finding).
    sign_off_artifact_type: str
    sign_off_artifact_id: str
    code: str
    language: str = ""
    title: str = ""
    summary: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReconcileResult:
    scanned: int = 0
    merged: int = 0
    resolved: int = 0
    captured: int = 0
    skipped_unmerged: int = 0
    gate_refused: int = 0
    errors: int = 0


class ReconcileAppliedRemediationsUseCase:
    def __init__(
        self,
        *,
        check_merged: Callable[[UUID, str], bool],
        resolve_finding: Callable[[UUID, str, str, str], bool],
        capture: Callable[..., object | None],
    ) -> None:
        # check_merged: (workspace_id, pr_url) -> bool  (integrations app surface)
        # resolve_finding: (workspace_id, task_id, reason, resolved_by) -> resolved?  (project app surface)
        # capture: capture_remediation_if_gated  (remediation gated capture)
        self._check_merged = check_merged
        self._resolve_finding = resolve_finding
        self._capture = capture

    def execute(self, candidates: Iterable[RemediationCandidate]) -> ReconcileResult:
        scanned = merged = resolved = captured = skipped = refused = errors = 0

        for candidate in candidates:
            scanned += 1
            try:
                if not self._check_merged(candidate.workspace_id, candidate.draft_pr_url):
                    skipped += 1
                    continue
                merged += 1

                # (a) Resolve the finding through the OWNING context — never a
                # cross-context Task write from here. Idempotent on their side.
                did_resolve = self._resolve_finding(
                    candidate.workspace_id,
                    candidate.finding_task_id,
                    "remediated",
                    "system:remediation_reconciler",
                )
                if did_resolve:
                    resolved += 1

                # (b) Offer the fix to the entry-gate. It independently re-verifies
                # all three conditions; if sign-off isn't approved it still refuses
                # (the finding stays resolved — resolution and admission are separate).
                entry = self._capture(
                    workspace_id=candidate.workspace_id,
                    finding_task_id=candidate.finding_task_id,
                    sign_off_artifact_type=candidate.sign_off_artifact_type,
                    sign_off_artifact_id=candidate.sign_off_artifact_id,
                    applied_pr_url=candidate.draft_pr_url,
                    code=candidate.code,
                    language=candidate.language,
                    title=candidate.title,
                    summary=candidate.summary,
                    tags=candidate.tags,
                    pr_applied=True,  # merge was VERIFIED against the host above
                )
                if entry is None:
                    refused += 1
                else:
                    captured += 1
            except Exception:
                # One bad candidate never sinks the batch — log with the finding id
                # (traceback preserved) and continue (the log-and-continue pattern the
                # rules sanction for per-item loops).
                errors += 1
                logger.exception(
                    "remediation_reconcile_item_failed workspace_id=%s finding_task_id=%s",
                    candidate.workspace_id,
                    candidate.finding_task_id,
                )

        result = ReconcileResult(
            scanned=scanned,
            merged=merged,
            resolved=resolved,
            captured=captured,
            skipped_unmerged=skipped,
            gate_refused=refused,
            errors=errors,
        )
        logger.info(
            "remediation_reconcile_summary scanned=%s merged=%s resolved=%s captured=%s "
            "skipped_unmerged=%s gate_refused=%s errors=%s",
            scanned,
            merged,
            resolved,
            captured,
            skipped,
            refused,
            errors,
        )
        return result
