"""The retry leg: a rejected draft PR frees its slot, and the queue drains.

THE BUG THIS CLOSES. The per-repo open-PR throttle counts a finding's draft PR
until that finding is RESOLVED, and only a MERGED PR resolves one. So a patch the
operator closed without merging held its slot forever. Reject three bad patches —
exactly what a careful operator does — and Auto-Sec could never open another PR
against that repository. The loop died silently, with no error and no state on the
board saying why. It was measured on the live demo workspace: after closing all
three open PRs on GitHub, the throttle still read 3/3.

Two halves, both required:

1. RELEASE — read each open draft PR's live state back from the code host. A
   closed-without-merge PR is stamped on its record (``pr_state="closed"``), which
   both stops the throttle counting it and tells the HUD the link is dead. The
   rejected attempt is KEPT, not erased: what was tried and turned down is the
   most useful context for the next attempt.
2. RETRY — for every repo now under its cap, re-dispatch the highest-risk finding
   that has a fix and no PR. This is what makes the backlog drain itself instead
   of needing someone to hand-crank it.

Every guardrail still lives in the ONE draft-PR engine; this only decides WHEN to
ask it again. Idempotent throughout: re-running settles nothing twice and opens no
duplicate PRs (``auto_draft_pr_for_finding`` no-ops on an existing record).
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

#: Cap the work one sweep will do, so a workspace with a large backlog can never
#: turn a single beat tick into a flood of host calls or PR opens.
_MAX_STATE_CHECKS_PER_SWEEP = 50
_MAX_RETRIES_PER_SWEEP = 10


@shared_task(name="infrastructure.ai.agents.tasks.release_rejected_draft_prs")
def release_rejected_draft_prs(workspace_id: str | None = None) -> dict:
    """Settle closed-without-merge draft PRs, then refill the freed slots."""
    from components.agents.infrastructure.tasks.agent_tasks import auto_draft_pr_for_finding
    from components.integrations.application.providers.vcs_provider import get_check_pr_merged_use_case
    from components.project.application.ports.record_finding_draft_pr_port import MarkDraftPrRejectedCommand
    from components.project.application.providers.project_provider import ProjectProvider

    workspaces = _target_workspaces(workspace_id)
    merge_check = get_check_pr_merged_use_case()
    reject = ProjectProvider.build_mark_finding_draft_pr_rejected_use_case()
    released: dict[str, set[str]] = {}
    checked = 0

    for ws_id in workspaces:
        for finding in ProjectProvider.build_task_lookup_port().list_draft_pr_findings(workspace_id=str(ws_id)):
            if checked >= _MAX_STATE_CHECKS_PER_SWEEP:
                break
            # Already settled — merged PRs belong to the remediation reconciler,
            # closed ones we have stamped before. No host call for either.
            if finding.merged or str(finding.pr_state or "").lower() == "closed":
                continue
            checked += 1
            status = merge_check.execute(workspace_id=str(ws_id), pr_url=finding.url)
            if not status.allowed or status.merged:
                continue
            if str(status.state or "").lower() != "closed":
                continue
            result = reject.execute(
                command=MarkDraftPrRejectedCommand(workspace_id=str(ws_id), task_id=str(finding.task_id))
            )
            if result.marked:
                released.setdefault(str(ws_id), set()).add(finding.repo)
                logger.info(
                    "draft_pr_released workspace_id=%s task_id=%s repo=%s pr=%s",
                    ws_id,
                    finding.task_id,
                    finding.repo,
                    finding.url,
                )

    retried = _refill_freed_slots(released, auto_draft_pr_for_finding)
    logger.info(
        "release_rejected_draft_prs checked=%s released=%s retried=%s",
        checked,
        sum(len(v) for v in released.values()),
        retried,
    )
    return {"checked": checked, "repos_freed": sum(len(v) for v in released.values()), "retried": retried}


def _target_workspaces(workspace_id: str | None) -> list[str]:
    from infrastructure.persistence.workspaces.models import Workspace

    if workspace_id:
        return [str(workspace_id)]
    return [str(w) for w in Workspace.objects.all_objects().values_list("id", flat=True)]


def _refill_freed_slots(released: dict[str, set[str]], dispatch) -> int:
    """Re-dispatch the highest-risk PR-less finding per repo that just freed a slot.

    Highest-risk first because the throttle means we are choosing WHICH finding
    gets the scarce slot — picking arbitrarily would hand it to whatever the DB
    returned first. Severity is the ranking we already have on the card.
    """
    from components.shared_kernel.domain.triage import design_change_brief
    from infrastructure.persistence.project.models import Task
    from infrastructure.persistence.workspaces.models import Workspace

    _SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
    retried = 0

    for ws_id, repos in released.items():
        owner_id = Workspace.objects.all_objects().filter(id=ws_id).values_list("workspace_owner_id", flat=True).first()
        if not owner_id:
            continue
        for repo in repos:
            if retried >= _MAX_RETRIES_PER_SWEEP:
                return retried
            candidates = []
            for task in Task.objects.filter(workspace_id=ws_id, source_type="ai.code_security"):
                meta = task.metadata or {}
                payload = meta.get("payload") or {}
                if str(payload.get("repo") or "") != repo:
                    continue
                if (payload.get("draft_pr") or {}).get("url"):
                    continue
                if (meta.get("triage") or {}).get("status") != "triaged":
                    continue
                if not str(payload.get("suggested_fix") or "").strip():
                    continue
                # Task #145: a design_change decline will never have a PR — its
                # artifact is the brief already on the card. Handing it the
                # scarce freed slot would burn the retry on a guaranteed skip.
                if design_change_brief(payload):
                    continue
                candidates.append((_SEVERITY_RANK.get(str(payload.get("severity") or "").lower(), 9), task.id))
            if not candidates:
                continue
            candidates.sort()
            task_id = candidates[0][1]
            dispatch.delay(
                workspace_id=str(ws_id),
                task_id=str(task_id),
                performed_by=str(owner_id),
                acting_agent="code_security_agent",
            )
            retried += 1
            logger.info("draft_pr_retry_dispatched workspace_id=%s repo=%s task_id=%s", ws_id, repo, task_id)
    return retried
