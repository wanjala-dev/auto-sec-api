"""Tests for the ``run_feedback_eval`` command (SEE-191, Phase 6d).

Two layers:

- **Isolation (unit):** the pass-through ``run_prompt_function`` builder and the
  case-normalisation helper — no DB, no LLM.
- **End-to-end (django_db):** seed a small newsletter feedback dataset, stub the
  ``WritingJudge`` at the class boundary (NO real LLM), run the command into a
  temp reports dir, and assert a report JSON lands with the expected ``_meta``
  the ``PromptEvalReportsViewSet`` reads.
"""

from __future__ import annotations

import json

import pytest

from components.agents.cli.management.commands.run_feedback_eval import (
    _build_pass_through_run_prompt_function,
    _normalise_case,
)


@pytest.mark.unit
class TestPassThroughAndNormalise:
    def test_pass_through_replays_generated_content(self):
        run = _build_pass_through_run_prompt_function("newsletter")
        case = {
            "expected_output": {"generated_content": "<p>Hello donors.</p>"},
        }
        draft = run(case)
        assert draft["body_html"] == "<p>Hello donors.</p>"
        # Not fabricated — the capture only snapshots the body.
        assert draft["title"] == ""
        assert draft["sections"] == []

    def test_pass_through_returns_none_without_content(self):
        run = _build_pass_through_run_prompt_function("newsletter")
        assert run({"expected_output": {"decision": "changes_requested"}}) is None
        assert run({}) is None

    def test_normalise_injects_context_from_input_data(self):
        case = {
            "id": "newsletter:n1",
            "input_data": {"grounding_texts": ["Fact A", "Fact B"]},
            "expected_output": {"generated_content": "<p>x</p>"},
        }
        enriched = _normalise_case(case, kind="newsletter")
        assert enriched["context"]["retrieved_context"] == ["Fact A", "Fact B"]
        assert enriched["context"]["kind"] == "newsletter"
        assert enriched["context"]["voice"] == {}
        # Original keys preserved.
        assert enriched["expected_output"]["generated_content"] == "<p>x</p>"


class _FakeJudge:
    """Stand-in for ``WritingJudge`` — returns a fixed multi-axis verdict, no LLM."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __call__(self, case, draft_payload):
        from components.agents.tests.prompt_eval.graders.model._types import (
            AxisScore,
            ModelGradeResult,
        )

        return ModelGradeResult(
            axes={
                "warmth": AxisScore(score=8),
                "specificity": AxisScore(score=7),
                "clarity_cta": AxisScore(score=8),
                "on_voice": AxisScore(score=9),
            }
        )


@pytest.mark.integration
@pytest.mark.django_db
class TestRunFeedbackEvalCommand:
    def _seed_negative(self, **overrides):
        from infrastructure.persistence.prompt_eval.models import PromptEvalExample

        defaults = dict(
            dataset_name="feedback-newsletter",
            case_id="newsletter:n1",
            category="unsupported_figure",
            goal="Generate a newsletter that passes human sign-off review.",
            input_data={
                "grounding_texts": ["The program served 40 students this term."],
                "prompt_id": "content.newsletter",
            },
            expected_output={
                "decision": "changes_requested",
                "codes": ["unsupported_figure"],
                "note": "The 100-kids figure isn't in the source.",
                "generated_content": (
                    "<h2>Term update</h2>"
                    "<p>This term our program served 40 students with warmth and "
                    "care, and we are grateful for every supporter who made it "
                    "possible. Here is what your generosity made real.</p>"
                ),
            },
            source_type="sign_off_feedback",
            feedback_decision="changes_requested",
            feedback_codes=["unsupported_figure"],
            feedback_note="The 100-kids figure isn't in the source.",
            artifact_type="newsletter",
            artifact_id="n1",
            workspace_id="w1",
        )
        defaults.update(overrides)
        return PromptEvalExample.objects.create(**defaults)

    def test_writes_report_with_expected_meta(self, monkeypatch, tmp_path):
        from django.core.management import call_command

        # Stub the judge at the class boundary the command imports — no LLM.
        monkeypatch.setattr(
            "components.agents.tests.prompt_eval.graders.writing.WritingJudge",
            _FakeJudge,
        )
        self._seed_negative()

        out_dir = tmp_path / "eval-reports"
        call_command(
            "run_feedback_eval",
            artifact_type=["newsletter"],
            output_dir=str(out_dir),
        )

        reports = list(out_dir.glob("feedback-newsletter-*.json"))
        assert len(reports) == 1
        data = json.loads(reports[0].read_text())

        assert data["case_count"] == 1
        assert data["dataset_name"] == "feedback-newsletter"
        meta = data["_meta"]
        assert meta["prompt_id"] == "writing.newsletter"
        assert meta["version"] == "active"
        assert meta["label"] == "sign_off_feedback"
        assert meta["source"] == "sign_off_feedback"
        assert meta["artifact_type"] == "newsletter"
        assert "created_at" in meta
        # An HTML twin is written alongside.
        assert (out_dir / meta["html_filename"]).exists()

    def test_skips_artifact_type_with_no_examples(self, monkeypatch, tmp_path):
        from django.core.management import call_command

        monkeypatch.setattr(
            "components.agents.tests.prompt_eval.graders.writing.WritingJudge",
            _FakeJudge,
        )
        out_dir = tmp_path / "eval-reports"
        # No rows seeded → nothing to grade, no report, no crash.
        call_command(
            "run_feedback_eval",
            artifact_type=["newsletter"],
            output_dir=str(out_dir),
        )
        assert not out_dir.exists() or not list(out_dir.glob("*.json"))
