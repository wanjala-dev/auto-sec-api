"""Unit tests for the ``EvalExample`` value object + its enums (SEE-190)."""

from __future__ import annotations

import pytest

from components.agents.domain.value_objects.eval_example import (
    EvalExample,
    ExampleSource,
    FeedbackDecision,
)


def _example(**overrides) -> EvalExample:
    kwargs = dict(
        dataset_name="feedback-newsletter",
        case_id="newsletter:n1",
        category="general",
        goal="Generate a newsletter that passes human sign-off review.",
        feedback_decision=FeedbackDecision.REJECTED,
        artifact_type="newsletter",
        artifact_id="n1",
    )
    kwargs.update(overrides)
    return EvalExample(**kwargs)


@pytest.mark.unit
class TestFeedbackDecisionEnum:
    def test_values(self):
        assert FeedbackDecision.APPROVED_OVERRIDE.value == "approved_override"
        assert FeedbackDecision.CHANGES_REQUESTED.value == "changes_requested"
        assert FeedbackDecision.REJECTED.value == "rejected"

    def test_is_str_enum(self):
        # str-Enum so ``.value`` and the member compare/serialise as strings.
        assert FeedbackDecision.REJECTED == "rejected"
        assert FeedbackDecision("rejected") is FeedbackDecision.REJECTED


@pytest.mark.unit
class TestExampleSourceEnum:
    def test_default_value(self):
        assert ExampleSource.SIGN_OFF_FEEDBACK.value == "sign_off_feedback"


@pytest.mark.unit
class TestEvalExample:
    def test_happy_path_defaults(self):
        example = _example()
        assert example.source_type is ExampleSource.SIGN_OFF_FEEDBACK
        assert example.input_data == {}
        assert example.expected_output == {}
        assert example.feedback_codes == []
        assert example.feedback_note == ""
        assert example.risk_band == ""
        assert example.reviewer_id == ""
        assert example.workspace_id == ""

    def test_is_frozen(self):
        example = _example()
        with pytest.raises(Exception):
            example.dataset_name = "other"  # type: ignore[misc]

    def test_missing_dataset_name_raises(self):
        with pytest.raises(ValueError, match="dataset_name"):
            _example(dataset_name="")

    def test_missing_case_id_raises(self):
        with pytest.raises(ValueError, match="case_id"):
            _example(case_id="")

    def test_missing_artifact_type_raises(self):
        with pytest.raises(ValueError, match="artifact_type"):
            _example(artifact_type="")

    def test_missing_artifact_id_raises(self):
        with pytest.raises(ValueError, match="artifact_id"):
            _example(artifact_id="")

    def test_carries_payloads(self):
        example = _example(
            input_data={"grounding_texts": ["a"], "prompt_id": "content.newsletter"},
            expected_output={"decision": "rejected", "codes": ["x"], "note": "n"},
            feedback_codes=["x", "y"],
            feedback_note="n",
            risk_band="red",
            reviewer_id="u1",
            workspace_id="w1",
        )
        assert example.input_data["prompt_id"] == "content.newsletter"
        assert example.expected_output["decision"] == "rejected"
        assert example.feedback_codes == ["x", "y"]
        assert example.risk_band == "red"
