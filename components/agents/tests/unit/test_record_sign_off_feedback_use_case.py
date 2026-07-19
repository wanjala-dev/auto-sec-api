"""Unit tests for ``RecordSignOffFeedbackUseCase`` (SEE-190).

Exercises the label policy + capture handling through an in-memory fake store
and a fake capture callable — no DB, no framework.
"""

from __future__ import annotations

import pytest

from components.agents.application.ports.eval_example_store_port import (
    EvalExampleStorePort,
)
from components.agents.application.use_cases.record_sign_off_feedback_use_case import (
    RecordSignOffFeedbackUseCase,
)
from components.agents.domain.value_objects.eval_example import (
    EvalExample,
    FeedbackDecision,
)


class _FakeStore(EvalExampleStorePort):
    """In-memory eval-example store honouring the unique-triple idempotency."""

    def __init__(self) -> None:
        self.examples: list[EvalExample] = []
        self._seen: set[tuple[str, str, FeedbackDecision]] = set()

    def add_example(self, example: EvalExample) -> str | None:
        key = (example.artifact_type, example.artifact_id, example.feedback_decision)
        if key in self._seen:
            return None
        self._seen.add(key)
        self.examples.append(example)
        return f"id-{len(self.examples)}"

    def list_examples(self, dataset_name: str) -> list[EvalExample]:
        return [e for e in self.examples if e.dataset_name == dataset_name]

    def list_recent_negatives(
        self, workspace_id: str, artifact_type: str, limit: int
    ) -> list[EvalExample]:
        # Not exercised by these label-policy tests; the SEE-191 few-shot use
        # case has its own dedicated coverage.
        return []


def _fake_capture(_artifact_type: str, _artifact_id: str) -> dict:
    return {
        "generated_content": "<p>Our progrma helped 100 kids.</p>",
        "grounding_texts": ["The program helped 100 children."],
        "prompt_id": "content.newsletter",
    }


def _use_case(store: _FakeStore, capture=_fake_capture) -> RecordSignOffFeedbackUseCase:
    return RecordSignOffFeedbackUseCase(store=store, capture=capture)


@pytest.mark.unit
class TestLabelPolicy:
    def test_approved_green_is_skipped(self):
        store = _FakeStore()
        result = _use_case(store).execute(
            artifact_type="newsletter",
            artifact_id="n1",
            decision="approved",
            risk_band="green",
            reason_codes=[],
            note="",
            actor_id="u1",
            workspace_id="w1",
        )
        assert result is None
        assert store.examples == []

    def test_approved_amber_is_skipped(self):
        store = _FakeStore()
        result = _use_case(store).execute(
            artifact_type="newsletter",
            artifact_id="n2",
            decision="approved",
            risk_band="amber",
            reason_codes=[],
            note="",
            actor_id="u1",
            workspace_id="w1",
        )
        assert result is None
        assert store.examples == []

    def test_approved_red_stores_override_positive(self):
        store = _FakeStore()
        result = _use_case(store).execute(
            artifact_type="newsletter",
            artifact_id="n3",
            decision="approved",
            risk_band="red",
            reason_codes=[],
            note="Confirmed the figure by hand.",
            actor_id="u1",
            workspace_id="w1",
        )
        assert result is not None
        assert len(store.examples) == 1
        stored = store.examples[0]
        assert stored.feedback_decision is FeedbackDecision.APPROVED_OVERRIDE
        assert stored.risk_band == "red"
        assert stored.dataset_name == "feedback-newsletter"
        assert stored.case_id == "newsletter:n3"
        # A positive override does NOT carry the generated content.
        assert "generated_content" not in stored.expected_output

    def test_changes_requested_stores_negative_with_codes_and_note(self):
        store = _FakeStore()
        result = _use_case(store).execute(
            artifact_type="writing_draft",
            artifact_id="d1",
            decision="changes_requested",
            risk_band="amber",
            reason_codes=["unsupported_figure", "off_voice"],
            note="The 100-kids number isn't in the source.",
            actor_id="u2",
            workspace_id="w9",
        )
        assert result is not None
        stored = store.examples[0]
        assert stored.feedback_decision is FeedbackDecision.CHANGES_REQUESTED
        assert stored.feedback_codes == ["unsupported_figure", "off_voice"]
        assert stored.feedback_note == "The 100-kids number isn't in the source."
        # category is the first code.
        assert stored.category == "unsupported_figure"
        assert stored.expected_output["decision"] == "changes_requested"
        assert stored.expected_output["codes"] == ["unsupported_figure", "off_voice"]
        # A negative example carries the rejected copy.
        assert stored.expected_output["generated_content"].startswith("<p>")
        # grounding snapshot flows into input_data.
        assert stored.input_data["grounding_texts"] == [
            "The program helped 100 children."
        ]
        assert stored.input_data["prompt_id"] == "content.newsletter"

    def test_rejected_stores_negative(self):
        store = _FakeStore()
        result = _use_case(store).execute(
            artifact_type="newsletter",
            artifact_id="n4",
            decision="rejected",
            risk_band="red",
            reason_codes=["fabricated_quote"],
            note="Invented a beneficiary quote.",
            actor_id="u3",
            workspace_id="w1",
        )
        assert result is not None
        stored = store.examples[0]
        assert stored.feedback_decision is FeedbackDecision.REJECTED
        assert stored.expected_output["generated_content"].startswith("<p>")

    def test_unknown_decision_is_skipped(self):
        store = _FakeStore()
        result = _use_case(store).execute(
            artifact_type="newsletter",
            artifact_id="n5",
            decision="deferred",
            risk_band="green",
            reason_codes=[],
            note="",
            actor_id="u1",
            workspace_id="w1",
        )
        assert result is None
        assert store.examples == []


@pytest.mark.unit
class TestCaptureHandling:
    def test_capture_none_is_tolerated(self):
        store = _FakeStore()
        use_case = RecordSignOffFeedbackUseCase(store=store, capture=None)
        result = use_case.execute(
            artifact_type="workflow_email",
            artifact_id="wf1",
            decision="rejected",
            risk_band="amber",
            reason_codes=["off_topic"],
            note="wrong audience",
            actor_id="u1",
            workspace_id="w1",
        )
        assert result is not None
        stored = store.examples[0]
        # Metadata-only example: empty grounding + prompt id, no generated content.
        assert stored.input_data == {"grounding_texts": [], "prompt_id": ""}
        assert "generated_content" not in stored.expected_output

    def test_capture_returning_none_is_tolerated(self):
        store = _FakeStore()
        use_case = RecordSignOffFeedbackUseCase(
            store=store, capture=lambda _t, _i: None
        )
        result = use_case.execute(
            artifact_type="budget_apply",
            artifact_id="b1",
            decision="changes_requested",
            risk_band="green",
            reason_codes=[],
            note="",
            actor_id="u1",
            workspace_id="w1",
        )
        assert result is not None
        stored = store.examples[0]
        assert stored.category == "general"
        assert stored.input_data == {"grounding_texts": [], "prompt_id": ""}


@pytest.mark.unit
class TestIdempotency:
    def test_duplicate_triple_returns_none(self):
        store = _FakeStore()
        use_case = _use_case(store)
        first = use_case.execute(
            artifact_type="newsletter",
            artifact_id="dup",
            decision="rejected",
            risk_band="red",
            reason_codes=["x"],
            note="n",
            actor_id="u1",
            workspace_id="w1",
        )
        second = use_case.execute(
            artifact_type="newsletter",
            artifact_id="dup",
            decision="rejected",
            risk_band="red",
            reason_codes=["x"],
            note="n",
            actor_id="u1",
            workspace_id="w1",
        )
        assert first is not None
        assert second is None
        assert len(store.examples) == 1
