"""Trigger one Opengrep scan of an allowlisted repo (ADR 0019 D3).

The trigger-time gates, in order — every rejection is a fast, honest 4xx before
anything is enqueued:

1. **Consent** — validate the ``owner/repo`` shape and confirm the workspace's
   VcsConnection allowlists it (via the integrations seam). The scan-time vend
   re-checks fail-closed, so a race with an allowlist edit cannot scan an
   unconsented repo.
2. **Budget (anti-spam)** — the scanning context's dispatch gate: at most ONE
   in-flight scan per repo, and one completed scan per cooldown window
   (default 1 hour, ``CODE_SECURITY_SCAN_COOLDOWN_SECONDS``). Back-to-back SCAN
   clicks are rejected server-side with ``scan_already_running`` /
   ``scan_cooldown`` (+ ``retry_after``); failed scans do NOT start a cooldown.

Provenance: manual triggers stamp ``triggered_by`` (the operator's user id) and
``trigger="manual"`` onto the run row via the shared scan choreography; the
post-merge verification rescan (#118) stamps ``trigger="merge_rescan"`` and is
the ONE caller allowed to pass ``bypass_cooldown=True`` (gate 2 only — gate 1,
consent, is never bypassed).
"""

from __future__ import annotations

import logging
import os

from components.code_security.domain.repo_reference import (
    InvalidRepoReferenceError,
    validate_repo_reference,
)

logger = logging.getLogger(__name__)

SOURCE = "code_security.opengrep"

# One user-visible scan per repo per hour by default (Henry, 2026-08-08: "lock
# repo scans so a user can only scan a repo once an hour — so we don't spam our
# system"). Env-overridable per deployment.
COOLDOWN_SECONDS = int(os.environ.get("CODE_SECURITY_SCAN_COOLDOWN_SECONDS", "3600"))


class RepoScanRejected(Exception):
    """The scan request failed a trigger-time gate. ``code`` is the API error token;
    ``retry_after`` (seconds) rides on budget rejections so surfaces can render a
    countdown."""

    def __init__(self, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class TriggerRepoScanUseCase:
    def prepare(self, *, workspace_id, repo: str, connection_id: str | None = None) -> dict:
        """Consent-gate only (no lock taken) — for callers that dispatch inline."""
        from components.integrations.application.providers.vcs_scan_access_provider import (
            resolve_scan_connection,
        )

        try:
            cleaned = validate_repo_reference(repo)
        except InvalidRepoReferenceError as exc:
            raise RepoScanRejected("invalid_repo", str(exc)) from exc

        connection = resolve_scan_connection(workspace_id, cleaned, connection_id)
        if connection is None:
            raise RepoScanRejected(
                "repo_not_allowlisted",
                f"{cleaned} is not on this workspace's VCS connection allowlist.",
            )
        return {
            "source": SOURCE,
            "workspace_id": str(workspace_id),
            "target_ref": cleaned,
            "connection_id": str(connection.id),
        }

    def execute(
        self,
        *,
        workspace_id,
        repo: str,
        connection_id: str | None = None,
        triggered_by=None,
        trigger: str = "manual",
        bypass_cooldown: bool = False,
    ) -> dict:
        """Gate (consent + budget) + enqueue. Returns ``{"task_id", "repo", "source"}``.

        ``trigger`` is the provenance the run row records (``manual`` /
        ``merge_rescan``). ``bypass_cooldown`` skips ONLY the completed-run
        cooldown — the one-in-flight invariant always holds. It exists for ONE
        caller: the post-merge verification rescan task (#118), so a just-merged
        fix verifies closed now instead of waiting out the anti-spam window.
        The consent gate is never bypassed. Manual (controller/CLI) and
        scheduled triggers keep the defaults.
        """
        from components.scanning.application.providers.scan_dispatch_provider import dispatch_scan
        from components.scanning.application.providers.scan_gate_provider import (
            check_and_lock_dispatch,
            release_dispatch_lock,
        )

        kwargs = self.prepare(workspace_id=workspace_id, repo=repo, connection_id=connection_id)

        gate = check_and_lock_dispatch(
            workspace_id=kwargs["workspace_id"],
            source=SOURCE,
            target_ref=kwargs["target_ref"],
            cooldown_seconds=COOLDOWN_SECONDS,
            bypass_cooldown=bypass_cooldown,
        )
        if not gate["allowed"]:
            if gate["reason"] == "cooldown":
                minutes = max(1, int((gate["retry_after"] or 0) / 60))
                raise RepoScanRejected(
                    "scan_cooldown",
                    f"{kwargs['target_ref']} was scanned recently — next scan available in ~{minutes} min.",
                    retry_after=gate["retry_after"],
                )
            raise RepoScanRejected(
                "scan_already_running",
                f"A scan of {kwargs['target_ref']} is already queued or running.",
            )

        try:
            async_result = dispatch_scan(
                **kwargs,
                trigger=trigger,
                triggered_by=str(triggered_by) if triggered_by else None,
            )
        except Exception:
            # The enqueue itself failed — free the lock so the operator can retry.
            release_dispatch_lock(workspace_id=kwargs["workspace_id"], source=SOURCE, target_ref=kwargs["target_ref"])
            raise
        logger.info(
            "code_security_scan_dispatched workspace_id=%s repo=%s task_id=%s trigger=%s triggered_by=%s",
            workspace_id,
            kwargs["target_ref"],
            async_result.id,
            trigger,
            triggered_by,
        )
        return {"task_id": str(async_result.id), "repo": kwargs["target_ref"], "source": SOURCE}
