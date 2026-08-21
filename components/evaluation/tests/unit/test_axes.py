"""The axis vocabulary is the contract between the suite, the verifiers and the judge.

These assert what ADR 0033 D2 actually says, in both directions. "Two axes are
deterministic" is only half the claim; the half that catches a mistake is that
the OTHER THREE ARE NOT. An axis quietly moved into the deterministic set would
be graded by a verifier that does not exist for it and score as unmeasured
forever, while the pass rate on the remaining axes looked healthy.
"""

from __future__ import annotations

import pytest

from components.evaluation.domain.value_objects.axes import (
    FIX_APPLIES,
    GROUNDED,
    NO_FABRICATED_ASSET,
    SCOPE_RESPECTED,
    SEVERITY_SOUND,
    TRIAGE_AXES,
    TRIAGE_AXIS_KEYS,
    Axis,
    Grader,
    axis_for,
    deterministic_axes,
    judged_axes,
)

pytestmark = pytest.mark.unit


class TestTheVocabularyIsExactlyWhatD2Names:
    def test_the_five_axes_and_no_others(self):
        assert set(TRIAGE_AXIS_KEYS) == {
            "grounded",
            "severity_sound",
            "fix_applies",
            "scope_respected",
            "no_fabricated_asset",
        }

    def test_keys_are_unique(self):
        assert len(TRIAGE_AXIS_KEYS) == len(set(TRIAGE_AXIS_KEYS)) == len(TRIAGE_AXES)

    def test_every_axis_carries_a_label_and_a_description(self):
        """A judged axis with no description is a rubric the judge invents."""
        for axis in TRIAGE_AXES:
            assert axis.label.strip(), axis.key
            assert axis.description.strip(), axis.key
            assert axis.description.rstrip().endswith("."), f"{axis.key}: description should be one sentence"


class TestTheGraderSplitIsD2s:
    """The load-bearing claim: which axes cost tokens and which do not."""

    def test_exactly_fix_applies_and_no_fabricated_asset_are_deterministic(self):
        assert {axis.key for axis in deterministic_axes()} == {"fix_applies", "no_fabricated_asset"}

    def test_the_other_three_need_the_judge(self):
        assert {axis.key for axis in judged_axes()} == {"grounded", "severity_sound", "scope_respected"}

    def test_the_two_sets_partition_the_vocabulary(self):
        deterministic = {axis.key for axis in deterministic_axes()}
        judged = {axis.key for axis in judged_axes()}
        assert deterministic & judged == set(), "an axis cannot be graded twice"
        assert deterministic | judged == set(TRIAGE_AXIS_KEYS), "every axis needs a grader"

    @pytest.mark.parametrize("axis", [FIX_APPLIES, NO_FABRICATED_ASSET])
    def test_deterministic_axes_do_not_require_a_judge(self, axis):
        assert axis.is_deterministic is True
        assert axis.requires_judge is False

    @pytest.mark.parametrize("axis", [GROUNDED, SEVERITY_SOUND, SCOPE_RESPECTED])
    def test_judged_axes_are_not_deterministic(self, axis):
        assert axis.requires_judge is True
        assert axis.is_deterministic is False

    def test_the_two_flags_are_exact_complements(self):
        """Cost estimation (D7) counts judge calls off these; a third state
        here would become an axis that is silently never graded."""
        for axis in TRIAGE_AXES:
            assert axis.is_deterministic != axis.requires_judge


class TestLookup:
    def test_a_known_key_round_trips(self):
        assert axis_for("grounded") is GROUNDED
        assert axis_for("fix_applies") is FIX_APPLIES

    def test_an_unknown_key_raises_rather_than_returning_none(self):
        """A silently-missing axis renders as a pass; a raise does not."""
        with pytest.raises(ValueError) as excinfo:
            axis_for("hallucination_free")

        assert "hallucination_free" in str(excinfo.value)
        assert "grounded" in str(excinfo.value), "the error should name the known axes"

    def test_lookup_is_not_fuzzy(self):
        with pytest.raises(ValueError):
            axis_for("Grounded")


class TestAxisValidation:
    def test_an_axis_without_a_description_is_rejected(self):
        with pytest.raises(ValueError) as excinfo:
            Axis(key="mystery", label="Mystery", description="   ", grader=Grader.JUDGED)

        assert "mystery" in str(excinfo.value)

    def test_an_axis_without_a_key_is_rejected(self):
        with pytest.raises(ValueError):
            Axis(key="", label="Nameless", description="Something.", grader=Grader.JUDGED)

    def test_a_valid_axis_is_accepted(self):
        axis = Axis(key="trajectory_sound", label="Trajectory", description="The path was sound.", grader=Grader.JUDGED)

        assert axis.key == "trajectory_sound"
        assert axis.requires_judge is True

    def test_as_dict_states_the_grader(self):
        payload = FIX_APPLIES.as_dict()

        assert payload["key"] == "fix_applies"
        assert payload["grader"] == "deterministic"
        assert payload["is_deterministic"] is True
