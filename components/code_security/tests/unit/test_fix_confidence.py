"""The per-rule confidence gate must FAIL CLOSED, or it is the old flag in disguise.

Every test here defends one way the gate could quietly become the hand-authored
``autofix: true`` it replaced: a small sample read as certainty, another model's
numbers borrowed, expired evidence trusted, a corrupt corpus read as an empty
one. The behavioural contract is `confidence_for` (the use-case door); tests
never reach into loader internals beyond pointing it at a corpus file.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from components.code_security.domain import fix_confidence as fc
from components.code_security.domain.fix_confidence import (
    AUTOFIX_LOWER_BOUND,
    AUTOFIX_MIN_TRIALS,
    EVIDENCE_MAX_AGE_DAYS,
    TIER_MEASURED_WEAK,
    TIER_PROVEN,
    TIER_UNPROVEN,
    FixConfidenceError,
    confidence_for,
    wilson_lower_bound,
)

pytestmark = pytest.mark.unit

_RULE = "autosec.python.sql-execute-format"
_MODEL = "claude-sonnet-4-20250514"


def _evidence_file(tmp_path, monkeypatch, text: str):
    path = tmp_path / "fix_confidence.yaml"
    path.write_text(text)
    monkeypatch.setattr(fc, "EVIDENCE_FILE", path)
    fc._load.cache_clear()
    return path


def _corpus(rule=_RULE, trials=20, passes=20, measured_at=None, model=_MODEL, extra=""):
    measured_at = (measured_at or date.today()).isoformat()
    return (
        f"corpus_digest: abc123\nmodel: {model}\nrules:\n"
        f"  {rule}:\n    trials: {trials}\n    passes: {passes}\n    measured_at: {measured_at}\n{extra}"
    )


@pytest.fixture(autouse=True)
def _reset_cache():
    yield
    fc._load.cache_clear()


class TestWilsonLowerBound:
    def test_perfect_small_sample_stays_below_the_autofix_bar(self):
        # 2/2 is the seduction this module exists to resist: a 100% ratio that
        # is statistically a coin flip.
        assert wilson_lower_bound(2, 2) < AUTOFIX_LOWER_BOUND

    def test_perfect_twenty_trials_clears_the_bar(self):
        assert wilson_lower_bound(20, 20) >= AUTOFIX_LOWER_BOUND

    def test_more_trials_at_the_same_rate_raise_the_bound(self):
        assert wilson_lower_bound(10, 10) < wilson_lower_bound(30, 30)

    def test_zero_trials_scores_zero_not_an_error(self):
        assert wilson_lower_bound(0, 0) == 0.0

    def test_bound_never_leaves_the_unit_interval(self):
        assert 0.0 <= wilson_lower_bound(0, 50) <= wilson_lower_bound(50, 50) <= 1.0


class TestFailClosedResolution:
    def test_no_evidence_file_resolves_unproven(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fc, "EVIDENCE_FILE", tmp_path / "absent.yaml")
        fc._load.cache_clear()

        verdict = confidence_for(_RULE, model=_MODEL)

        assert verdict.tier == TIER_UNPROVEN
        assert not verdict.autofix_permitted

    def test_unmeasured_rule_resolves_unproven(self, tmp_path, monkeypatch):
        _evidence_file(tmp_path, monkeypatch, _corpus())

        verdict = confidence_for("autosec.python.some-new-rule", model=_MODEL)

        assert verdict.tier == TIER_UNPROVEN
        assert "never been measured" in verdict.reason

    def test_evidence_from_another_model_does_not_transfer(self, tmp_path, monkeypatch):
        _evidence_file(tmp_path, monkeypatch, _corpus(model="gpt-4"))

        verdict = confidence_for(_RULE, model=_MODEL)

        assert verdict.tier == TIER_UNPROVEN
        assert "gpt-4" in verdict.reason and not verdict.autofix_permitted

    def test_undeclared_running_model_resolves_unproven(self, tmp_path, monkeypatch):
        # A caller that cannot say what model is running cannot be told a rule
        # is proven — passing "" must not borrow the corpus's numbers.
        _evidence_file(tmp_path, monkeypatch, _corpus())

        assert confidence_for(_RULE, model="").tier == TIER_UNPROVEN

    def test_expired_evidence_resolves_unproven(self, tmp_path, monkeypatch):
        stale = date.today() - timedelta(days=EVIDENCE_MAX_AGE_DAYS + 1)
        _evidence_file(tmp_path, monkeypatch, _corpus(measured_at=stale))

        verdict = confidence_for(_RULE, model=_MODEL)

        assert verdict.tier == TIER_UNPROVEN
        assert "expiry" in verdict.reason

    def test_blank_rule_id_resolves_unproven(self, tmp_path, monkeypatch):
        _evidence_file(tmp_path, monkeypatch, _corpus())

        assert confidence_for("", model=_MODEL).tier == TIER_UNPROVEN


class TestTiering:
    def test_twenty_clean_trials_are_proven_and_autofix_permitted(self, tmp_path, monkeypatch):
        _evidence_file(tmp_path, monkeypatch, _corpus(trials=20, passes=20))

        verdict = confidence_for(_RULE, model=_MODEL)

        assert verdict.tier == TIER_PROVEN
        assert verdict.autofix_permitted

    def test_below_the_trial_floor_is_measured_weak_even_when_perfect(self, tmp_path, monkeypatch):
        _evidence_file(tmp_path, monkeypatch, _corpus(trials=AUTOFIX_MIN_TRIALS - 1, passes=AUTOFIX_MIN_TRIALS - 1))

        verdict = confidence_for(_RULE, model=_MODEL)

        assert verdict.tier == TIER_MEASURED_WEAK
        assert not verdict.autofix_permitted
        assert str(AUTOFIX_MIN_TRIALS) in verdict.reason  # the reason names the floor

    def test_a_one_in_three_rule_is_measured_weak(self, tmp_path, monkeypatch):
        # The actual live baseline that created this task.
        _evidence_file(tmp_path, monkeypatch, _corpus(trials=15, passes=5))

        verdict = confidence_for(_RULE, model=_MODEL)

        assert verdict.tier == TIER_MEASURED_WEAK
        assert not verdict.autofix_permitted

    def test_label_shape_carries_the_numbers_and_the_reason(self, tmp_path, monkeypatch):
        _evidence_file(tmp_path, monkeypatch, _corpus(trials=20, passes=18))

        label = confidence_for(_RULE, model=_MODEL).as_label()

        assert set(label) == {"tier", "reason", "trials", "passes", "lower_bound"}
        assert label["trials"] == 20 and label["passes"] == 18


class TestCorpusLoading:
    def test_malformed_corpus_raises_instead_of_reading_as_empty(self, tmp_path, monkeypatch):
        # A corrupt file silently treated as "no evidence" would be
        # indistinguishable from the honest empty state — it must be loud.
        _evidence_file(tmp_path, monkeypatch, "rules:\n  some.rule:\n    trials: 5\n")

        with pytest.raises(FixConfidenceError):
            confidence_for("some.rule", model=_MODEL)

    def test_passes_exceeding_trials_raises(self, tmp_path, monkeypatch):
        _evidence_file(tmp_path, monkeypatch, _corpus(trials=3, passes=7))

        with pytest.raises(FixConfidenceError):
            confidence_for(_RULE, model=_MODEL)
