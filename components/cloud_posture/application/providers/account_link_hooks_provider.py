"""Registry-facing hooks for the AWS CSPM pillar's post-scan side effects.

Composition root (providers are the allowed slot for own-context infrastructure
imports). Two hooks the scanner registry wires into the generic scan task —
both about the ACCOUNT LINK, because the scan attempt IS the per-account role
verification, in both directions:

- **post-ingest** (run COMPLETED): promote the scanned account link to
  VERIFIED — the scan proved the role works.
- **failure** (run FAILED): mark the account link FAILED, degrading that one
  account without blocking the rest of the org.

The legacy ``CloudPostureScan``/``CloudPostureFinding`` snapshot write that
used to live here is DELETED (audit R2): ``ScanRun`` + the Finding SSOT are the
only stores — the HUD posture card reads them via ``posture_summary``.

Both hooks are best-effort by the registry's contract — the caller logs and
continues.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _set_link_status(connection_id, account_id: str, status: str) -> None:
    """Best-effort update of an account link's verification status (no-op if absent)."""
    from infrastructure.persistence.integrations.models import AwsAccountLink

    AwsAccountLink.objects.filter(connection_id=connection_id, account_id=account_id).update(status=status)


def build_post_ingest_hook():
    """(run facts) → account link VERIFIED."""

    def _hook(*, run_id, workspace_id, target_ref, result, connection_id=None, account_id="", **_) -> None:
        from infrastructure.persistence.integrations.models import AwsAccountLink

        account = account_id or target_ref
        if connection_id:
            # The scan proved the role in this account — promote the link to VERIFIED.
            _set_link_status(connection_id, account, AwsAccountLink.Status.VERIFIED)
        logger.info(
            "cloud_posture_post_ingest run_id=%s account=%s checks=%s failed=%s",
            run_id,
            account,
            result.total_checks,
            result.failed_count,
        )

    return _hook


def build_failure_hook():
    """(run facts) → account link FAILED."""

    def _hook(*, workspace_id, target_ref, connection_id=None, account_id="", **_) -> None:
        from infrastructure.persistence.integrations.models import AwsAccountLink

        account = account_id or target_ref
        if connection_id:
            _set_link_status(connection_id, account, AwsAccountLink.Status.FAILED)
        logger.info(
            "cloud_posture_scan_failure_hook workspace_id=%s account=%s link_marked_failed=%s",
            workspace_id,
            account,
            bool(connection_id),
        )

    return _hook
