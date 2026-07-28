"""Compute the workspace's opinionated risk score (read-only rollup, CQRS read).

Gathers the two inputs the score needs — live attack paths (the dominant, exploitable
signal) and open finding severity counts — through ports, then hands them to the pure
``risk_score_calculator``. A few cheap indexed COUNTs + one ranked path read; no mutation.
"""

from __future__ import annotations

from uuid import UUID

from components.cloud_graph.domain.services.risk_score_calculator import RiskScore, calculate


class GetRiskScoreUseCase:
    def __init__(self, *, finding_store, attack_path_store) -> None:
        self._findings = finding_store
        self._paths = attack_path_store

    def execute(self, workspace_id: UUID) -> RiskScore:
        critical = self._findings.count_findings(workspace_id, severity="critical", status="open")
        high = self._findings.count_findings(workspace_id, severity="high", status="open")
        medium = self._findings.count_findings(workspace_id, severity="medium", status="open")
        paths = self._paths.list_for_workspace(workspace_id, limit=200)
        return calculate(
            attack_path_scores=[p.risk_score for p in paths],
            critical=critical,
            high=high,
            medium=medium,
        )
