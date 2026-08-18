"""SAST re-scan triggers: the nightly beat fan-out + the post-merge rescan (#118).

Beat entry: for every workspace opted into ``feature.code_security``, enqueue one
Opengrep scan per allowlisted repo of its CONNECTED VcsConnections (via the
integrations seam — the allowlist IS the consent boundary). Self-gates on the
flag; dark until opt-in — the P1 trigger answer is manual + nightly-when-flag-on.

Merge entry (#118): when the remediation reconciler confirms a draft PR merged
(a NEW resolved transition), it dispatches ``code_security.rescan_repo_after_remediation``
BY NAME for the affected repo — a cooldown-exempt verification scan, so the fix
verifies closed now instead of waiting out the anti-spam window or the next beat.

Fingerprint-based identity (D4) makes any re-scan cheap on the SSOT:
unchanged findings bump ``last_seen``, fixed ones stop being observed and the
existing resolve machinery closes them, new ones are genuinely new.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)

_SOURCE = "code_security.opengrep"


@shared_task(name="code_security.schedule_repo_scans", soft_time_limit=240, time_limit=300)
def schedule_repo_scans() -> dict[str, Any]:
    """Fan out Opengrep scans over opted-in workspaces' allowlisted repos."""
    from components.integrations.application.providers.vcs_scan_access_provider import (
        list_scannable_repos,
    )
    from components.scanning.application.providers.scan_dispatch_provider import dispatch_scan
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )
    from infrastructure.persistence.workspaces.models import Workspace

    flags = get_feature_flags_provider()
    scheduled = 0
    for workspace in Workspace.active.only("id").iterator():
        try:
            if not flags.is_feature_enabled("feature.code_security", workspace_id=workspace.id):
                continue
        except Exception:
            logger.exception("code_security flag check failed workspace=%s", workspace.id)
            continue
        for repo, connection_id in list_scannable_repos(workspace.id):
            dispatch_scan(
                source=_SOURCE,
                workspace_id=str(workspace.id),
                target_ref=repo,
                connection_id=connection_id,
                trigger="schedule",  # provenance: the nightly beat, not an operator
            )
            scheduled += 1

    logger.info("schedule_repo_scans scheduled=%d", scheduled)
    return {"success": True, "scheduled": scheduled}


@shared_task(
    name="code_security.rescan_repo_after_remediation",
    bind=True,
    max_retries=3,
    soft_time_limit=60,
    time_limit=90,
)
def rescan_repo_after_remediation(self, workspace_id: str, repo: str) -> dict[str, Any]:
    """Cooldown-exempt verification rescan after a remediation PR merged (#118).

    Dispatched BY NAME by the remediation reconciler when it confirms a draft
    PR merged (a NEW resolved transition — the reconciler owns that gate and
    never re-fires for already-stamped findings). The scan itself flows the
    normal spine: FindingObserved → findings SSOT dedup → the fixed finding is
    no longer observed and the existing resolve machinery keeps it closed.

    Gates, in order — only the cooldown is exempt:

    1. ``feature.code_security`` — same self-gate as the nightly beat.
    2. Consent (allowlist) — via ``TriggerRepoScanUseCase`` — NEVER bypassed;
       a repo removed from the allowlist since the PR opened is rejected here.
    3. Budget — ``bypass_cooldown=True`` skips the completed-run cooldown so
       the fix verifies closed NOW; the one-in-flight invariant still holds.
       If a scan is already running it may predate the merge commit, so this
       task retries (bounded) instead of trusting a possibly-stale scan.

    Idempotent: a duplicate delivery either finds the rescan in flight
    (rejected → bounded retry → gives up gracefully) or re-scans — and a
    re-scan is a no-op on the fingerprint-identity SSOT.
    """
    from celery.exceptions import MaxRetriesExceededError

    from components.code_security.application.use_cases.trigger_repo_scan_use_case import (
        RepoScanRejected,
        TriggerRepoScanUseCase,
    )
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )

    logger.info(
        "rescan_repo_after_remediation started workspace_id=%s repo=%s task_id=%s",
        workspace_id,
        repo,
        self.request.id,
    )

    if not get_feature_flags_provider().is_feature_enabled("feature.code_security", workspace_id=workspace_id):
        logger.info("rescan_repo_after_remediation skipped_flag_off workspace_id=%s repo=%s", workspace_id, repo)
        return {"dispatched": False, "reason": "flag_off"}

    try:
        result = TriggerRepoScanUseCase().execute(
            workspace_id=workspace_id,
            repo=repo,
            trigger="merge_rescan",  # provenance on the run row
            bypass_cooldown=True,  # the ONE caller allowed to carry the exemption
        )
    except RepoScanRejected as exc:
        if exc.code == "scan_already_running":
            # The in-flight scan may have checked the tree out BEFORE the merge
            # commit — retry (bounded) so verification runs against merged state.
            try:
                raise self.retry(countdown=600, exc=exc)
            except MaxRetriesExceededError:
                logger.warning(
                    "rescan_repo_after_remediation gave_up_running workspace_id=%s repo=%s",
                    workspace_id,
                    repo,
                )
                return {"dispatched": False, "reason": "scan_already_running"}
        # Consent says no (repo un-allowlisted since the PR opened) or the ref is
        # malformed — honor the gate; the nightly beat remains the safety net.
        logger.warning(
            "rescan_repo_after_remediation rejected workspace_id=%s repo=%s code=%s",
            workspace_id,
            repo,
            exc.code,
        )
        return {"dispatched": False, "reason": exc.code}

    logger.info(
        "rescan_repo_after_remediation completed workspace_id=%s repo=%s scan_task_id=%s",
        workspace_id,
        repo,
        result["task_id"],
    )
    return {"dispatched": True, "scan_task_id": result["task_id"]}
