"""Celery task: reconcile applied remediation PRs into the corpus (ADR 0012 P4a).

The driving adapter for :class:`ReconcileAppliedRemediationsUseCase`. It:

1. reads the board for findings that carry an OPEN remediation draft PR and are not
   yet resolved (a persistence read of ``project`` — the sanctioned pattern
   ``BoardFindingFactsRepository`` uses; NOT a ``components.project.infrastructure``
   import), materializing lean :class:`RemediationCandidate` DTOs;
2. wires the three cross-context reaches to the OWNING contexts' *application*
   surfaces (integrations = merge check, project = resolve-finding, remediation =
   the gated capture); and
3. runs the use case, which merge-checks each candidate and, for the merged ones,
   resolves the finding + offers it to the entry-gate.

Celery discipline (``.claude/rules/performance.md`` §5/7, celery-tasks skill): pass
only the workspace id (not objects), iterate with ``.iterator(chunk_size=...)``,
idempotent (re-run safe — already-resolved / already-captured is a no-op), and
structured INFO logging at entry + exit. A ``workspace_id=None`` sweep reconciles
every workspace that has a connected VCS connection.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

_LOG_WATCH_SOURCE = "ai.log_watch"
_CHUNK = 200


def _iter_candidate_tasks(workspace_id: str | None):
    """Yield board Tasks with an open remediation draft PR that are not yet resolved.

    A persistence read of the ``project`` model (allowed — reading another context's
    persistence is not importing its infrastructure). Filters in the DB where
    possible (draft_pr present) and screens the resolved marker in Python (it lives
    under two possible JSON keys), so a resolved finding is never re-processed.
    """
    from infrastructure.persistence.project.models import Task

    qs = Task.objects.filter(source_type=_LOG_WATCH_SOURCE, metadata__payload__draft_pr__isnull=False)
    if workspace_id is not None:
        qs = qs.filter(workspace_id=workspace_id)
    qs = qs.only("id", "workspace_id", "title", "metadata").order_by("id")

    for task in qs.iterator(chunk_size=_CHUNK):
        meta = task.metadata or {}
        payload = meta.get("payload") or {}
        draft_pr = payload.get("draft_pr") or {}
        pr_url = draft_pr.get("url")
        if not pr_url:
            continue
        # Skip already-resolved findings (idempotency at the source).
        triage = meta.get("triage") or {}
        if str(triage.get("status", "")).lower() == "resolved" or payload.get("resolved"):
            continue
        yield task, meta, payload, pr_url


def _build_candidate(task, meta: dict, payload: dict, pr_url: str):
    """Map a board Task onto a RemediationCandidate the gated capture can consume.

    The sign-off artifact + fix code are read off the finding's own metadata — the
    gate re-verifies them, so this is untrusted input the gate independently checks.
    """
    from components.remediation.application.use_cases.reconcile_applied_remediations_use_case import (
        RemediationCandidate,
    )

    sign_off = payload.get("sign_off") or meta.get("sign_off") or {}
    suggested = payload.get("suggested_fix") or ""
    proposed = payload.get("proposed_patch") or {}
    code = (proposed.get("code") if isinstance(proposed, dict) else "") or suggested or ""
    language = (proposed.get("language") if isinstance(proposed, dict) else "") or payload.get("language") or ""

    return RemediationCandidate(
        workspace_id=task.workspace_id,
        finding_task_id=str(task.id),
        draft_pr_url=pr_url,
        sign_off_artifact_type=str(sign_off.get("artifact_type") or "remediation"),
        sign_off_artifact_id=str(sign_off.get("artifact_id") or ""),
        code=code,
        language=language,
        title=(task.title or "")[:200],
        summary=str(payload.get("probable_cause") or ""),
        tags=tuple(str(t) for t in (payload.get("tags") or []) if t),
    )


def _candidates(workspace_id: str | None):
    for task, meta, payload, pr_url in _iter_candidate_tasks(workspace_id):
        yield _build_candidate(task, meta, payload, pr_url)


@shared_task(name="remediation.reconcile_applied_remediations", soft_time_limit=240, time_limit=300)
def reconcile_applied_remediations(workspace_id: str | None = None) -> dict:
    """Reconcile merged remediation PRs → resolved findings → gated corpus entries.

    ``workspace_id`` scopes the sweep to one workspace; ``None`` sweeps all. Safe to
    enqueue repeatedly (idempotent). Returns the reconcile counters."""
    from components.integrations.application.providers.vcs_provider import get_check_pr_merged_use_case
    from components.project.application.ports.resolve_finding_task_port import ResolveFindingTaskCommand
    from components.project.application.providers.project_provider import ProjectProvider
    from components.remediation.application.handlers.remediation_capture_handler import (
        capture_remediation_if_gated,
    )
    from components.remediation.application.use_cases.reconcile_applied_remediations_use_case import (
        ReconcileAppliedRemediationsUseCase,
    )

    logger.info("reconcile_applied_remediations started workspace_id=%s", workspace_id)

    merge_check = get_check_pr_merged_use_case()
    resolve_uc = ProjectProvider.build_resolve_finding_task_use_case()

    def check_merged(ws_id, pr_url: str) -> bool:
        return merge_check.execute(workspace_id=str(ws_id), pr_url=pr_url).merged

    def resolve_finding(ws_id, task_id: str, reason: str, resolved_by: str) -> bool:
        result = resolve_uc.execute(
            command=ResolveFindingTaskCommand(
                workspace_id=str(ws_id),
                task_id=task_id,
                reason=reason,
                resolved_by=resolved_by,
            )
        )
        # Report only a NEW transition so the reconciler's ``resolved`` counter is a
        # true count of findings this cycle closed (an already-resolved finding is a
        # no-op the summary should not re-count).
        return bool(result.resolved and not result.already_resolved)

    use_case = ReconcileAppliedRemediationsUseCase(
        check_merged=check_merged,
        resolve_finding=resolve_finding,
        capture=capture_remediation_if_gated,
    )
    result = use_case.execute(_candidates(workspace_id))

    summary = {
        "scanned": result.scanned,
        "merged": result.merged,
        "resolved": result.resolved,
        "captured": result.captured,
        "skipped_unmerged": result.skipped_unmerged,
        "gate_refused": result.gate_refused,
        "errors": result.errors,
    }
    logger.info("reconcile_applied_remediations completed workspace_id=%s summary=%s", workspace_id, summary)
    return summary
