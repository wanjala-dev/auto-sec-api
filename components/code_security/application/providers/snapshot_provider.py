"""Composition root: the per-repo scan snapshot post-ingest hook (ADR 0019 P1).

``build_post_ingest_hook`` is what the scanner registry resolves for
``code_security.opengrep`` — after a completed run it persists ONE
``RepoScanSnapshot`` row (severity counts + the resolved commit provenance from the
adapter's ``code_security.scan_meta`` artifact). Best-effort by the registry's
policy: a snapshot failure never fails the completed scan.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC

logger = logging.getLogger(__name__)

_SCAN_META_KIND = "code_security.scan_meta"


def build_post_ingest_hook():
    """The registry-facing hook: (run_id, workspace_id, target_ref, result) → snapshot row."""

    def _hook(*, run_id, workspace_id, target_ref, result, **_) -> None:
        # **_ swallows run facts this hook doesn't need (connection_id/account_id).
        persist_repo_scan_snapshot(run_id=run_id, workspace_id=workspace_id, target_ref=target_ref, result=result)

    return _hook


def persist_repo_scan_snapshot(*, run_id, workspace_id, target_ref, result) -> None:
    """Record the run's snapshot row (idempotent on ``scan_run_id``)."""
    from infrastructure.persistence.code_security.models import RepoScanSnapshot

    meta = _scan_meta(result)
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in result.findings:
        severity = finding.severity.value
        if severity in counts:
            counts[severity] += 1

    RepoScanSnapshot.objects.update_or_create(
        scan_run_id=run_id,
        defaults={
            "workspace_id": workspace_id,
            "repo": str(target_ref)[:200],
            "commit_sha": str(meta.get("commit_sha") or "")[:64],
            "engine_version": str(meta.get("engine_version") or result.engine_version or "")[:32],
            "total_findings": len(result.findings),
            "critical_count": counts["critical"],
            "high_count": counts["high"],
            "medium_count": counts["medium"],
            "low_count": counts["low"],
        },
    )
    logger.info(
        "code_security_snapshot_persisted run_id=%s repo=%s commit=%s findings=%d",
        run_id,
        target_ref,
        str(meta.get("commit_sha") or "")[:12],
        len(result.findings),
    )


def list_recent_snapshots(workspace_id, *, repo: str = "", limit: int = 20):
    """The HUD tile's read: recent snapshot rows, newest first (optionally per repo).

    Provider-owned so the controller never touches the ORM (composition-root slot).
    """
    from infrastructure.persistence.code_security.models import RepoScanSnapshot

    queryset = RepoScanSnapshot.objects.filter(workspace_id=workspace_id).order_by("-created_at")
    if repo:
        queryset = queryset.filter(repo=repo)
    return list(queryset[: max(1, min(int(limit), 100))])


def utc_isoformat(value) -> str:
    """Aware-UTC ISO stamp for a snapshot timestamp.

    Deployments run ``USE_TZ=False`` (naive rows whose values ARE UTC) while tests
    run aware — normalizing here keeps every API stamp unambiguous for clients
    (the repo-status read already normalizes the same way)."""
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).isoformat()


def latest_snapshots_by_repo(workspace_id, repos: list[str]) -> dict[str, dict]:
    """The newest snapshot summary per repo — the repo-status read's counts join.

    Constant query count regardless of repo count (the repository does it in two
    queries) — never a per-repo fetch. The ORM lives in the repository; this
    composition-root slot only shapes the API-facing dicts.
    """
    from components.code_security.infrastructure.repositories.repo_scan_snapshot_repository import (
        latest_snapshot_rows_by_repo,
    )

    return {
        repo: {
            "scan_run_id": str(row.scan_run_id),
            "commit_sha": row.commit_sha,
            "engine_version": row.engine_version,
            "total_findings": row.total_findings,
            "critical_count": row.critical_count,
            "high_count": row.high_count,
            "medium_count": row.medium_count,
            "low_count": row.low_count,
            "created_at": utc_isoformat(row.created_at),
        }
        for repo, row in latest_snapshot_rows_by_repo(workspace_id, repos).items()
    }


def _scan_meta(result) -> dict:
    for artifact in getattr(result, "artifacts", ()) or ():
        if getattr(artifact, "kind", "") == _SCAN_META_KIND:
            try:
                data = json.loads(artifact.content)
                return data if isinstance(data, dict) else {}
            except ValueError:
                logger.warning("code_security_scan_meta_not_json")
                return {}
    return {}
