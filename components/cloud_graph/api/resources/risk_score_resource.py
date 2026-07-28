"""Output DTO — the workspace risk score for the HUD gauge."""

from __future__ import annotations

from components.cloud_graph.domain.services.risk_score_calculator import RiskScore


class RiskScoreResource:
    @staticmethod
    def of(score: RiskScore) -> dict:
        # value = risk (0–100, higher worse); posture = 100-value (for a health-style gauge);
        # factors = the explainable breakdown of what drives the score.
        return score.to_dict()
