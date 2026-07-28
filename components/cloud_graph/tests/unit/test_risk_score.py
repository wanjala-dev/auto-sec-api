"""Risk-score calculator (pure) + the gathering use case (fakes). Deterministic."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from components.cloud_graph.application.use_cases.get_risk_score_use_case import GetRiskScoreUseCase
from components.cloud_graph.domain.services.risk_score_calculator import calculate

pytestmark = pytest.mark.unit


class TestCalculator:
    def test_clean_workspace_is_zero_low(self):
        s = calculate(attack_path_scores=[], critical=0, high=0, medium=0)
        assert s.value == 0 and s.band == "low" and s.posture == 100

    def test_attack_paths_dominate(self):
        # one worst-80 path → 40 pts, no findings → value 40, band medium
        s = calculate(attack_path_scores=[80.0], critical=0, high=0, medium=0)
        assert s.value == 40 and s.band == "medium"
        ap = next(f for f in s.factors if f.key == "attack_paths")
        assert ap.points == 40 and "1 live toxic path" in ap.detail

    def test_extra_paths_add_marginal_bump_and_cap(self):
        # worst 90 → 45, +3 extra paths ×5 = 15 → 60 (hits the cap)
        s = calculate(attack_path_scores=[90.0, 70.0, 60.0, 55.0], critical=0, high=0, medium=0)
        ap = next(f for f in s.factors if f.key == "attack_paths")
        assert ap.points == 60  # capped

    def test_findings_capped_so_volume_cannot_drown_signal(self):
        s = calculate(attack_path_scores=[], critical=100, high=100, medium=100)
        findings = next(f for f in s.factors if f.key == "findings")
        assert findings.points == 35  # capped, not 830

    def test_posture_is_inverse_and_bands(self):
        s = calculate(attack_path_scores=[95.0], critical=5, high=10, medium=0)
        # attack: min(60, 47.5)=47.5→48 ; findings: min(35, 30+20)=35 → value ~83 critical
        assert s.band == "critical" and s.value >= 75
        assert s.posture == 100 - s.value

    def test_to_dict_shape(self):
        d = calculate(attack_path_scores=[80.0], critical=1, high=0, medium=0).to_dict()
        assert set(d) == {"value", "band", "posture", "factors"}
        assert {f["key"] for f in d["factors"]} == {"attack_paths", "findings"}


class _FakeFindings:
    def __init__(self, counts):
        self._counts = counts  # {"critical": n, "high": n, "medium": n}

    def count_findings(self, workspace_id, *, severity=None, status=None, **kw):
        assert status == "open"
        return self._counts.get(severity, 0)


class _FakePaths:
    def __init__(self, scores):
        self._scores = scores

    def list_for_workspace(self, workspace_id, **kw):
        return [SimpleNamespace(risk_score=s) for s in self._scores]


class TestUseCase:
    def test_gathers_inputs_and_scores(self):
        uc = GetRiskScoreUseCase(
            finding_store=_FakeFindings({"critical": 2, "high": 4, "medium": 1}),
            attack_path_store=_FakePaths([80.0, 65.0]),
        )
        s = uc.execute(uuid.uuid4())
        # attack: min(60, 40 + 5) = 45 ; findings: min(35, 12 + 8 + 0.3) = 20.3→20 ; value 65
        assert s.value == 65 and s.band == "high"
