"""Integration tests for ``DjangoEvalExampleRepository`` + the
``PromptEvalExample`` model idempotency (SEE-190).

Proves the ``(artifact_type, artifact_id, feedback_decision)`` unique triple
deduplicates a replayed decision, and that add/list round-trips a full example
back into its value-object shape.
"""

from __future__ import annotations

import pytest

from components.agents.domain.value_objects.eval_example import (
    EvalExample,
    ExampleSource,
    FeedbackDecision,
)
from components.agents.infrastructure.repositories.django_eval_example_repository import (
    DjangoEvalExampleRepository,
)


def _example(**overrides) -> EvalExample:
    kwargs = dict(
        dataset_name="feedback-newsletter",
        case_id="newsletter:n1",
        category="unsupported_figure",
        goal="Generate a newsletter that passes human sign-off review.",
        feedback_decision=FeedbackDecision.CHANGES_REQUESTED,
        artifact_type="newsletter",
        artifact_id="n1",
        input_data={"grounding_texts": ["fact"], "prompt_id": "content.newsletter"},
        expected_output={"decision": "changes_requested", "codes": ["x"], "note": "n"},
        feedback_codes=["unsupported_figure"],
        feedback_note="fix the number",
        risk_band="amber",
        reviewer_id="u1",
        workspace_id="w1",
    )
    kwargs.update(overrides)
    return EvalExample(**kwargs)


@pytest.mark.integration
@pytest.mark.django_db
class TestDjangoEvalExampleRepository:
    def test_add_then_list_round_trips(self):
        repo = DjangoEvalExampleRepository()
        example_id = repo.add_example(_example())
        assert example_id is not None

        listed = repo.list_examples("feedback-newsletter")
        assert len(listed) == 1
        stored = listed[0]
        assert isinstance(stored, EvalExample)
        assert stored.feedback_decision is FeedbackDecision.CHANGES_REQUESTED
        assert stored.source_type is ExampleSource.SIGN_OFF_FEEDBACK
        assert stored.feedback_codes == ["unsupported_figure"]
        assert stored.input_data["prompt_id"] == "content.newsletter"
        assert stored.expected_output["decision"] == "changes_requested"
        assert stored.risk_band == "amber"
        assert stored.reviewer_id == "u1"
        assert stored.workspace_id == "w1"

    def test_duplicate_triple_is_idempotent(self):
        repo = DjangoEvalExampleRepository()
        first = repo.add_example(_example())
        second = repo.add_example(_example(feedback_note="different note ignored"))
        assert first is not None
        assert second is None
        assert len(repo.list_examples("feedback-newsletter")) == 1

    def test_same_artifact_different_decision_is_a_new_row(self):
        repo = DjangoEvalExampleRepository()
        repo.add_example(_example(feedback_decision=FeedbackDecision.CHANGES_REQUESTED))
        # A later reject on the same artifact is a distinct triple.
        second = repo.add_example(
            _example(
                feedback_decision=FeedbackDecision.REJECTED,
                expected_output={"decision": "rejected", "codes": [], "note": ""},
            )
        )
        assert second is not None
        assert len(repo.list_examples("feedback-newsletter")) == 2

    def test_list_scopes_to_dataset(self):
        repo = DjangoEvalExampleRepository()
        repo.add_example(_example())
        repo.add_example(
            _example(
                dataset_name="feedback-writing_draft",
                artifact_type="writing_draft",
                case_id="writing_draft:d1",
                artifact_id="d1",
            )
        )
        assert len(repo.list_examples("feedback-newsletter")) == 1
        assert len(repo.list_examples("feedback-writing_draft")) == 1
