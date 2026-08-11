"""Adapter: read a draft-PR finding's facts from ``project.Task``.

Implements :class:`FindingFactsPort`. Same sanctioned cross-context read pattern
the ``report`` (``FindingSourcePort`` → ``BoardFindingRepository``) and
``remediation`` (``FindingRemediationFactsPort`` → ``BoardFindingFactsRepository``)
contexts use: the integrations context defines its own port shaped to the draft-PR
flow's need, and this infrastructure adapter reads the shared ``project``
persistence model. Reading ``infrastructure.persistence.project.models`` is a
persistence read, NOT a ``components.project.infrastructure`` import — it does not
cross the component-infrastructure boundary the architecture tests guard.

The source-type gate (the draft-PR-actionable sources: ``ai.log_watch`` +
``ai.code_security``, ADR 0019 P2) and workspace scope live here, matching the old
inline ``_require_actionable_finding`` query: a task from another workspace, of a
non-actionable source type, or with a malformed id resolves to ``None``.
"""

from __future__ import annotations

from components.integrations.application.ports.finding_facts_port import (
    ActionableFinding,
    DraftPrPatchGap,
    FindingFactsPort,
)
from components.project.application.ports.record_finding_draft_pr_port import (
    draft_pr_candidate_filter,
    get_draft_pr,
)
from components.shared_kernel.domain.triage import PR_REMEDIABLE_SOURCE_TYPES

# The finding sources the ONE draft-PR engine acts on (ADR 0017 D0). A new source
# joins the shared-kernel tuple together with its patch strategy in the use case —
# never a second engine. ONE definition (shared kernel) so the engine's gate and
# the read paths that decide whether to OFFER the PR affordance can never
# disagree (the pre-fix bug: container findings got the affordance, then the
# engine refused them as ``finding_not_found``).
ACTIONABLE_SOURCES = PR_REMEDIABLE_SOURCE_TYPES


class BoardFindingFactsReader(FindingFactsPort):
    def get_actionable_finding(self, *, workspace_id: str, task_id: str) -> ActionableFinding | None:
        from infrastructure.persistence.project.models import Task

        try:
            row = Task.objects.filter(id=task_id, workspace_id=workspace_id, source_type__in=ACTIONABLE_SOURCES).first()
        except (ValueError, TypeError):
            # Malformed id (Task pks are integers) — same answer as absent.
            row = None
        if row is None:
            return None
        return ActionableFinding(
            id=str(row.id),
            title=row.title,
            metadata=row.metadata or {},
            source_type=row.source_type or "",
        )

    def count_open_draft_prs(self, *, workspace_id: str, source_type: str, repo: str) -> int:
        """Open (recorded, unresolved) draft PRs for ``source_type`` against ``repo``.

        A merged PR's finding is resolved by the remediation reconciler
        (``metadata.triage.status = "resolved"`` / ``payload.resolved``), which
        removes it from this count — the throttle window frees as PRs land.

        A CLOSED-without-merge PR frees the window too, once the sweep has stamped
        ``draft_pr.pr_state = "closed"``. Counting rejected PRs was the silent
        killer: three patches the operator turned down permanently consumed a
        repo's entire budget, so Auto-Sec could never open another PR against it —
        and rejecting bad patches is exactly what a careful operator does. The
        throttle exists to protect merge RATE, not to punish rejection.
        """
        from infrastructure.persistence.project.models import Task

        rows = Task.objects.filter(
            workspace_id=workspace_id,
            source_type=source_type,
            metadata__payload__draft_pr__repo=repo,
        ).values_list("metadata", flat=True)
        open_count = 0
        for metadata in rows:
            meta = metadata or {}
            payload = meta.get("payload") or {}
            record = payload.get("draft_pr") or {}
            if not record.get("url"):
                continue
            triage = meta.get("triage") or {}
            if str(triage.get("status", "")).lower() == "resolved" or payload.get("resolved"):
                continue
            if str(record.get("pr_state") or "").lower() == "closed" and not record.get("merged"):
                continue
            open_count += 1
        return open_count

    def list_draft_pr_patch_gaps(self, *, workspace_id: str = "", limit: int = 500) -> tuple[DraftPrPatchGap, ...]:
        """Sweep for draft-PR records that carry a ``url`` but no stored ``diff``.

        The candidate set comes from ``draft_pr_candidate_filter()`` — the SAME
        canonical path definition the writer and the remediation reconciler use,
        so a writer-side move of the record can never silently empty this sweep.
        The "has a diff" test is then applied in Python: JSON key-ABSENCE is what
        distinguishes a legacy record, and that is expressed portably here rather
        than as a backend-specific JSON lookup (the suite runs on SQLite, the
        cluster on Postgres — one predicate, both backends).
        """
        from infrastructure.persistence.project.models import Task

        rows = Task.objects.filter(**draft_pr_candidate_filter())
        if workspace_id:
            rows = rows.filter(workspace_id=workspace_id)

        gaps: list[DraftPrPatchGap] = []
        for task_id, task_workspace_id, metadata in (
            rows.order_by("id").values_list("id", "workspace_id", "metadata").iterator(chunk_size=500)
        ):
            record = get_draft_pr(metadata or {})
            if not record.get("url"):
                continue
            if str(record.get("diff") or "").strip():
                continue  # already renders inline — nothing to repair
            gaps.append(
                DraftPrPatchGap(
                    workspace_id=str(task_workspace_id),
                    task_id=str(task_id),
                    pr_url=str(record.get("url") or ""),
                    repo=str(record.get("repo") or ""),
                )
            )
            if len(gaps) >= limit:
                break
        return tuple(gaps)
