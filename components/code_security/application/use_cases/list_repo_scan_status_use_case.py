"""Per-repo scan status — the CODE REPOS card's read (ADR 0019 D3).

Composes the two published seams: the workspace's scannable repos (integrations —
the consent boundary) with each repo's latest run facts (scanning — the history
owner): last-scanned timestamp, status, duration, trigger provenance, whether a
scan is in flight, and the remaining cooldown so surfaces can disable SCAN with
an honest countdown instead of letting the click bounce off the server gate.
"""

from __future__ import annotations

from datetime import UTC, datetime

SOURCE = "code_security.opengrep"


def _as_utc(value: datetime) -> datetime:
    """Normalize a run timestamp to aware-UTC. Deployments run ``USE_TZ=False``
    (naive rows whose values ARE UTC) while tests run aware — subtracting across
    the two raises ``TypeError``, so every comparison goes through here."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class ListRepoScanStatusUseCase:
    def execute(self, *, workspace_id, cooldown_seconds: int) -> list[dict]:
        from components.integrations.application.providers.vcs_scan_access_provider import (
            list_scannable_repos,
        )
        from components.scanning.application.providers.scan_gate_provider import latest_runs_for

        repos = list_scannable_repos(workspace_id)
        history = latest_runs_for(workspace_id, SOURCE, [repo for repo, _ in repos])

        now = datetime.now(UTC)
        rows: list[dict] = []
        for repo, connection_id in repos:
            facts = history.get(repo) or {}
            last_scanned_at = facts.get("last_scanned_at")
            cooldown_remaining = 0
            if last_scanned_at is not None and facts.get("last_status") == "completed" and not facts.get("in_flight"):
                elapsed = (now - _as_utc(last_scanned_at)).total_seconds()
                cooldown_remaining = max(0, int(cooldown_seconds - elapsed))
            rows.append(
                {
                    "repo": repo,
                    "connection_id": connection_id,
                    "last_scanned_at": _as_utc(last_scanned_at).isoformat() if last_scanned_at else None,
                    "last_status": facts.get("last_status") or None,
                    "last_run_id": facts.get("last_run_id"),
                    "duration_seconds": facts.get("duration_seconds"),
                    "trigger": facts.get("trigger"),
                    "triggered_by_id": facts.get("triggered_by_id"),
                    "in_flight": bool(facts.get("in_flight")),
                    "cooldown_remaining": cooldown_remaining,
                }
            )
        return rows
