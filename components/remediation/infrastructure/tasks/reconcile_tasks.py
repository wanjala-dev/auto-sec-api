"""Reconciler implementation for merged remediation PRs (ADR 0012 P4a).

The heavy-lifting half of the beat-scheduled reconciler, kept out of the thin
``workers/tasks.py`` Celery shim (bounded-context structure: workers are primary
adapters, this infrastructure module owns the composition + run). It delegates to
``ReconcileMergedRemediationsUseCase`` (assembled by the remediation provider),
which scans findings carrying an open draft PR, verifies each PR's merge via the
integrations ``VcsPort``, resolves the finding on a verified merge, and offers the
fix to the D1 entry-gate with a VERIFIED ``pr_applied=True``.

Idempotent (already-resolved findings and findings already holding a
RemediationEntry are no-ops) and safe to run every cycle.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def run_reconcile_merged_remediations() -> dict[str, Any]:
    """Sweep open draft-PR findings; resolve + capture the ones whose PR merged.

    Returns a small counts dict for the beat task to log. Fans out over all
    workspaces internally via the ORM iterator — no arguments needed."""
    from components.remediation.application.providers.remediation_provider import (
        build_reconcile_merged_remediations_use_case,
    )

    result = build_reconcile_merged_remediations_use_case().execute()
    return {
        "scanned": result.scanned,
        "merged": result.merged,
        "resolved": result.resolved,
        "captured": result.captured,
    }
