"""SEE-207 — adversarial red-team suite.

Runs the ``red_team_v1`` corpus (injection, jailbreak, exfiltration, goal
manipulation) against the deterministic defence: the index-time injection scan
(SEE-200). Injection-shaped cases must be flagged; non-injection cases (goal
manipulation, benign) must NOT be — that both proves the scan doesn't over-trigger
and documents which cases rely on the other layers (risk gate SEE-203, autonomous
cap SEE-201, role-scoped retrieval SEE-199, MCP denylist SEE-204).

The LLM-judge red-team pass over those non-scan cases is the informational e2e
follow-up (env-gated like the other quality evals) — this module is the always-on
regression net for the scan, and the single source of truth for the corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.knowledge.domain.value_objects.injection_scan import (
    is_injection_suspected,
)

_DATASET = Path(__file__).parent / "datasets" / "red_team_v1.json"
_CASES = json.loads(_DATASET.read_text())["cases"]
_SCAN_CASES = [c for c in _CASES if c["scan_flags"]]
_NON_SCAN_CASES = [c for c in _CASES if not c["scan_flags"]]


class TestCorpusShape:
    def test_corpus_is_well_formed(self):
        data = json.loads(_DATASET.read_text())
        assert data["_meta"]["case_count"] == len(_CASES)
        ids = [c["id"] for c in _CASES]
        assert len(ids) == len(set(ids)), "case ids must be unique"
        for case in _CASES:
            assert {"id", "category", "input", "defense", "scan_flags"} <= set(case)

    def test_covers_the_core_attack_categories(self):
        categories = {c["category"] for c in _CASES}
        assert {"injection", "jailbreak", "exfiltration", "goal_manipulation"} <= categories


class TestScanDefenceCoverage:
    @pytest.mark.parametrize("case", _SCAN_CASES, ids=[c["id"] for c in _SCAN_CASES])
    def test_injection_shaped_cases_are_flagged(self, case):
        assert is_injection_suspected(case["input"]) is True

    @pytest.mark.parametrize("case", _NON_SCAN_CASES, ids=[c["id"] for c in _NON_SCAN_CASES])
    def test_non_injection_cases_are_not_flagged(self, case):
        # Goal-manipulation and benign inputs are not injection-shaped — they are
        # defended by the risk gate / autonomous cap / role-scoping, not the scan.
        # Flagging them would be over-triggering.
        assert is_injection_suspected(case["input"]) is False
