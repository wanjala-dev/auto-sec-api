"""Output DTO — the materialized ATT&CK coverage heatmap for the HUD."""

from __future__ import annotations

from components.findings.application.ports.attck_coverage_port import CoverageSnapshot


class AttckCoverageResource:
    @staticmethod
    def from_snapshot(snapshot: CoverageSnapshot, *, refreshing: bool) -> dict:
        return {
            "coverage": snapshot.coverage,
            "technique_count": snapshot.technique_count,
            "finding_count": snapshot.finding_count,
            "computed_at": snapshot.computed_at.isoformat() if snapshot.computed_at else None,
            # A recompute was just enqueued — the HUD can show a "refreshing" hint and
            # poll again shortly (the heatmap is eventually-consistent, not real-time).
            "refreshing": refreshing,
        }
