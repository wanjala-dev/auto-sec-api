"""Adapter: mirror scan-run lifecycle transitions into the shared audit log (audit R4).

A scan is an operator-initiated action against CUSTOMER infrastructure — for a
security product whose posture is "this will be probed by hackers", the immutable
trail must cover it (SOC2-shaped buyers ask to see exactly this). Before this
adapter, sign-offs and member removal were audited but scans were not.

Delegates to the ``audit`` context's application surface (``AuditLogPort.record``
via the audit repository provider) — the same funnel ``remediation_audit_adapter``
and ``kernel_sign_off_audit_adapter`` use. One immutable ``EntityAuditLog`` row per
lifecycle transition of the run:

    entity_type    = "scanning.scanrun"  (app_label.model → resolves the ContentType)
    entity_id      = the ScanRun id
    field_name     = "status"
    previous/new   = the lifecycle transition ("" → running → completed | failed)
    actor_id       = the triggering user (manual runs), None for system/schedule
    reason         = "<source> scan of <target> (<trigger>)" + outcome facts

Best-effort by the shared posture: an audit-write failure is logged loud
(ERROR + traceback, structured context) but never fails the scan — the run row
and findings are already the truth; monitoring catches the trail gap.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_ENTITY_TYPE = "scanning.scanrun"
_FIELD_NAME = "status"


def _resolve_actor_id(run) -> str | None:
    """``ScanRun.triggered_by_id`` is a SOFT reference; ``EntityAuditLog.actor``
    is a hard FK. Resolve before writing — an unresolvable id (e.g. a since-
    deleted account) must not corrupt the trail insert; the raw id is preserved
    in ``reason`` by the caller either way."""
    if not run.triggered_by_id:
        return None
    from infrastructure.persistence.users.models import CustomUser

    actor_id = str(run.triggered_by_id)
    if CustomUser.objects.filter(id=actor_id).exists():
        return actor_id
    return None


def _record(*, run, previous: str, new: str, reason: str) -> None:
    try:
        from components.audit.application.providers.entity_audit_log_repository_provider import (
            get_entity_audit_log_repository_provider,
        )

        if run.triggered_by_id:
            reason = f"{reason} triggered_by={run.triggered_by_id}"
        get_entity_audit_log_repository_provider().repository().record(
            workspace_id=str(run.workspace_id),
            entity_type=_ENTITY_TYPE,
            entity_id=str(run.id),
            field_name=_FIELD_NAME,
            previous_value=previous,
            new_value=new,
            actor_id=_resolve_actor_id(run),
            reason=reason,
        )
    except Exception:
        # Deliberate, documented broad catch: the scan must not crash on an
        # audit-store hiccup — but a scan with no trail row is a governance GAP,
        # so raise it loud + alertable rather than passing silently.
        logger.exception(
            "scan_run_audit_write_failed ALERT governance_trail_gap run_id=%s workspace_id=%s transition=%s->%s",
            run.id,
            run.workspace_id,
            previous,
            new,
        )


def audit_scan_started(run) -> None:
    """The run was created and is executing — the operator/system action itself."""
    _record(
        run=run,
        previous="",
        new="running",
        reason=f"{run.source} scan of {run.target_ref} triggered ({run.trigger})",
    )


def audit_scan_completed(run) -> None:
    _record(
        run=run,
        previous="running",
        new="completed",
        reason=(
            f"{run.source} scan of {run.target_ref} completed ({run.trigger}): "
            f"{run.failed_count} findings across {run.total_checks} checks"
        ),
    )


def audit_scan_failed(run, *, error: str = "") -> None:
    # Coarse error token only — a raw exception string could carry internal
    # paths/ARNs into the trail readers' surfaces.
    detail = f": {error[:120]}" if error else ""
    _record(
        run=run,
        previous="running",
        new="failed",
        reason=f"{run.source} scan of {run.target_ref} failed ({run.trigger}){detail}",
    )
