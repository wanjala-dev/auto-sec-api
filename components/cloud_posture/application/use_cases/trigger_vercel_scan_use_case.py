"""Trigger one Vercel posture scan for a connection's consented team (ADR 0021 D3).

Rides the scanning SPINE end-to-end (the code_security shape, deliberately NOT the
legacy cloud_posture AWS task path): the anti-spam gate reads/writes ``ScanRun``
history via ``check_and_lock_dispatch``, the dispatch goes through the generic
``dispatch_scan`` → ``run_scan`` → ``run_scan_and_ingest`` choreography (which
records the run with trigger/triggered_by/engine-version, releases the dispatch
lock on failure, and emits the findings to the SSOT).

The trigger-time gates, in order — every rejection is a fast, honest 4xx before
anything is enqueued:

1. **Consent/shape** — the team must be a well-formed team id/slug (the same
   validator that guards the scan Job's env — an unpinned or malformed team never
   reaches Prowler).
2. **Budget (anti-spam)** — at most ONE in-flight scan per team, one completed
   scan per cooldown window (default 1 hour, ``VERCEL_SCAN_COOLDOWN_SECONDS``);
   failed scans do NOT start a cooldown.
"""

from __future__ import annotations

import logging
import os

from components.cloud_posture.domain.posture_provider import VERCEL_POSTURE_PROVIDER
from components.cloud_posture.domain.scan_targets import (
    InvalidVercelScanTargetError,
    validate_vercel_scan_target,
)

logger = logging.getLogger(__name__)

SOURCE = VERCEL_POSTURE_PROVIDER.source

# One user-visible scan per team per hour by default — the same anti-spam stance as
# code_security's repo cooldown. Env-overridable per deployment.
COOLDOWN_SECONDS = int(os.environ.get("VERCEL_SCAN_COOLDOWN_SECONDS", "3600"))


class VercelScanRejected(Exception):
    """The scan request failed a trigger-time gate. ``code`` is the API error token;
    ``retry_after`` (seconds) rides on budget rejections so surfaces can render a
    countdown."""

    def __init__(self, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class TriggerVercelScanUseCase:
    def execute(self, *, workspace_id, connection_id, team: str, trigger: str = "manual", triggered_by=None) -> dict:
        """Gate (shape + budget) + enqueue. Returns ``{"task_id", "team", "source"}``."""
        from components.scanning.application.providers.scan_dispatch_provider import dispatch_scan
        from components.scanning.application.providers.scan_gate_provider import (
            check_and_lock_dispatch,
            release_dispatch_lock,
        )

        try:
            cleaned = validate_vercel_scan_target(team)
        except InvalidVercelScanTargetError as exc:
            raise VercelScanRejected("invalid_team", str(exc)) from exc

        gate = check_and_lock_dispatch(
            workspace_id=str(workspace_id),
            source=SOURCE,
            target_ref=cleaned,
            cooldown_seconds=COOLDOWN_SECONDS,
        )
        if not gate["allowed"]:
            if gate["reason"] == "cooldown":
                minutes = max(1, int((gate["retry_after"] or 0) / 60))
                raise VercelScanRejected(
                    "scan_cooldown",
                    f"Team {cleaned} was scanned recently — next scan available in ~{minutes} min.",
                    retry_after=gate["retry_after"],
                )
            raise VercelScanRejected(
                "scan_already_running",
                f"A scan of team {cleaned} is already queued or running.",
            )

        try:
            async_result = dispatch_scan(
                source=SOURCE,
                workspace_id=str(workspace_id),
                target_ref=cleaned,
                connection_id=str(connection_id),
                account_id=cleaned,
                trigger=trigger,
                triggered_by=str(triggered_by) if triggered_by else None,
                params={"provider": VERCEL_POSTURE_PROVIDER.token},
            )
        except Exception:
            # The enqueue itself failed — free the lock so the operator can retry.
            release_dispatch_lock(workspace_id=str(workspace_id), source=SOURCE, target_ref=cleaned)
            raise
        logger.info(
            "vercel_posture_scan_dispatched workspace_id=%s team=%s task_id=%s trigger=%s triggered_by=%s",
            workspace_id,
            cleaned,
            async_result.id,
            trigger,
            triggered_by,
        )
        return {"task_id": str(async_result.id), "team": cleaned, "source": SOURCE}
