"""Severity-weighted repo risk ranking — "which repo is most vulnerable" (ADR 0019 P2).

Deterministic READ over the pillar's own snapshot rows (the per-scan severity
counts ``persist_repo_scan_snapshot`` already records): each scannable repo's
LATEST completed snapshot is weighted critical-first and ranked. No LLM, no new
persistence — the code_security agent's ``rank_repos_by_risk`` tool wraps this.

A repo with no snapshot yet ranks last with ``scanned=False`` — an honest "not
scanned" beats a fabricated zero.
"""

from __future__ import annotations

# Severity weights, critical-dominant: one critical outranks any pile of lows,
# mirroring how the board floor (high+critical) prioritises attention.
_WEIGHTS = {"critical": 10, "high": 5, "medium": 2, "low": 1}


class RankReposByRiskUseCase:
    def execute(self, *, workspace_id) -> list[dict]:
        from components.code_security.application.providers.snapshot_provider import (
            list_recent_snapshots,
        )
        from components.integrations.application.providers.vcs_scan_access_provider import (
            list_scannable_repos,
        )

        repos = [repo for repo, _ in list_scannable_repos(workspace_id)]
        latest: dict[str, object] = {}
        # Newest-first snapshot rows: the first row seen per repo is its latest scan.
        for row in list_recent_snapshots(workspace_id, limit=100):
            latest.setdefault(row.repo, row)

        rows: list[dict] = []
        for repo in repos:
            snapshot = latest.get(repo)
            if snapshot is None:
                rows.append(
                    {
                        "repo": repo,
                        "scanned": False,
                        "risk_score": 0,
                        "critical": 0,
                        "high": 0,
                        "medium": 0,
                        "low": 0,
                        "total_findings": 0,
                        "commit_sha": "",
                    }
                )
                continue
            score = (
                _WEIGHTS["critical"] * snapshot.critical_count
                + _WEIGHTS["high"] * snapshot.high_count
                + _WEIGHTS["medium"] * snapshot.medium_count
                + _WEIGHTS["low"] * snapshot.low_count
            )
            rows.append(
                {
                    "repo": repo,
                    "scanned": True,
                    "risk_score": score,
                    "critical": snapshot.critical_count,
                    "high": snapshot.high_count,
                    "medium": snapshot.medium_count,
                    "low": snapshot.low_count,
                    "total_findings": snapshot.total_findings,
                    "commit_sha": (snapshot.commit_sha or "")[:12],
                }
            )
        rows.sort(key=lambda r: (r["scanned"], r["risk_score"]), reverse=True)
        return rows
