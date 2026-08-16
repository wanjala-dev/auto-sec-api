"""The frozen corpus must stay internally true, or every measurement lies.

A fixture whose line numbers drift off its source content (a formatter reflow
did exactly this the day the corpus was authored) measures the advisor against
the WRONG lines and the number it produces is noise. These checks make that
class of rot loud.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from components.agents.infrastructure.evaluation.sast_fix_eval import load_fixtures
from components.code_security.domain.remediation_guidance import (
    STRATEGY_GUIDANCE_ONLY,
    guidance_for,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

#: The sink each rule's matched region must actually contain — the proof the
#: fixture's line numbers point at the flagged code, not at a comment above it.
_RULE_SINKS = {
    "autosec.python.sql-execute-format": "execute",
    "autosec.python.subprocess-shell-true": "subprocess.run",
    "autosec.python.yaml-load-unsafe": ".load(",
    "autosec.python.requests-verify-disabled": "verify=False",
    "autosec.python.jwt-verify-disabled": "jwt.decode",
    "autosec.python.pickle-load-untrusted": "pickle.loads",
}


def _fixtures():
    return load_fixtures(FIXTURES_DIR)


class TestCorpusIntegrity:
    def test_the_corpus_is_not_empty_and_covers_both_classes(self):
        fixtures = _fixtures()
        assert len(fixtures) >= 6
        assert {f.fix_class for f in fixtures} == {"A", "B"}

    @pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f.id)
    def test_line_numbers_point_at_the_flagged_sink(self, fixture):
        sink = _RULE_SINKS[fixture.rule_id]
        assert sink in fixture.matched_region, (
            f"{fixture.id}: lines {fixture.start_line}-{fixture.end_line} of "
            f"{fixture.path} do not contain '{sink}' — the fixture's span has "
            "drifted off its source content (formatter reflow?). Re-align the "
            "manifest to the file before trusting any measurement."
        )

    @pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f.id)
    def test_every_rule_resolves_to_remediation_guidance(self, fixture):
        assert guidance_for(fixture.rule_id) is not None, (
            f"{fixture.id}: {fixture.rule_id} has no remediation-class binding — "
            "the harness would measure an unguided advisor and report it as the "
            "guided one."
        )

    @pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f.id)
    def test_class_b_fixtures_expect_decline_and_class_a_expect_patch(self, fixture):
        expected = {"A": "patch", "B": "decline"}[fixture.fix_class]
        assert fixture.expected == expected

    def test_class_b_fixtures_bind_to_guidance_only_classes(self):
        """Class B is not an opinion — it is the per-class strategy decision.

        A ``decline`` fixture whose class is ``llm_plus_oracles`` would punish
        the advisor for producing the patch its strategy tells it to produce.
        """
        for fixture in _fixtures():
            if fixture.fix_class != "B":
                continue
            guidance = guidance_for(fixture.rule_id)
            assert guidance.strategy == STRATEGY_GUIDANCE_ONLY, (
                f"{fixture.id}: class-B fixture but {fixture.rule_id} binds to strategy '{guidance.strategy}'"
            )

    def test_fixture_ids_are_unique_and_match_filenames(self):
        fixtures = _fixtures()
        ids = [f.id for f in fixtures]
        assert len(ids) == len(set(ids))
        on_disk = {p.stem for p in FIXTURES_DIR.glob("*.json")}
        assert set(ids) == on_disk
