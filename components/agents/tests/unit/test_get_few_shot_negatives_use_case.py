"""Unit tests for ``GetFewShotNegativesUseCase`` (SEE-191, Phase 6d).

Exercises the reviewer-feedback few-shot block builder through an in-memory
fake store — no DB, no framework. Asserts the fail-closed empty-string cases,
the block content (codes + note), the note truncation, and — critically — that
the store is queried with the exact workspace + artifact_type + cap (isolation).
"""

from __future__ import annotations

import pytest

from components.agents.application.config import feedback_injection_config as cfg
from components.agents.application.ports.eval_example_store_port import (
    EvalExampleStorePort,
)
from components.agents.application.use_cases.get_few_shot_negatives_use_case import (
    GetFewShotNegativesUseCase,
)
from components.agents.domain.value_objects.eval_example import (
    EvalExample,
    FeedbackDecision,
)


class _RecordingStore(EvalExampleStorePort):
    """Fake store that records the filter args it was queried with."""

    def __init__(self, negatives: list[EvalExample] | None = None) -> None:
        self._negatives = negatives or []
        self.calls: list[dict] = []

    def add_example(self, example: EvalExample) -> str | None:  # pragma: no cover
        raise NotImplementedError

    def list_examples(self, dataset_name: str) -> list[EvalExample]:  # pragma: no cover
        raise NotImplementedError

    def list_recent_negatives(
        self, workspace_id: str, artifact_type: str, limit: int
    ) -> list[EvalExample]:
        self.calls.append(
            {"workspace_id": workspace_id, "artifact_type": artifact_type, "limit": limit}
        )
        # Honour the cap the way a real adapter would.
        return list(self._negatives)[:limit]


def _negative(**overrides) -> EvalExample:
    kwargs = dict(
        dataset_name="feedback-newsletter",
        case_id="newsletter:n1",
        category="unsupported_figure",
        goal="Generate a newsletter that passes human sign-off review.",
        feedback_decision=FeedbackDecision.CHANGES_REQUESTED,
        artifact_type="newsletter",
        artifact_id="n1",
        feedback_codes=["unsupported_figure", "off_voice"],
        feedback_note="The 100-kids figure isn't in the source facts.",
    )
    kwargs.update(overrides)
    return EvalExample(**kwargs)


@pytest.mark.unit
class TestGetFewShotNegativesUseCase:
    def test_returns_empty_when_disabled(self, monkeypatch):
        monkeypatch.setattr(cfg, "FEEDBACK_FEW_SHOT_ENABLED", False)
        store = _RecordingStore([_negative()])
        result = GetFewShotNegativesUseCase(store).execute(
            workspace_id="w1", artifact_type="newsletter"
        )
        assert result == ""
        # Disabled short-circuits before touching the store.
        assert store.calls == []

    def test_returns_empty_when_no_workspace(self):
        store = _RecordingStore([_negative()])
        result = GetFewShotNegativesUseCase(store).execute(
            workspace_id="", artifact_type="newsletter"
        )
        assert result == ""
        assert store.calls == []

    def test_returns_empty_when_no_negatives(self):
        store = _RecordingStore([])
        result = GetFewShotNegativesUseCase(store).execute(
            workspace_id="w1", artifact_type="newsletter"
        )
        assert result == ""
        # It DID query (workspace + type present); just found nothing.
        assert len(store.calls) == 1

    def test_includes_codes_and_note(self):
        store = _RecordingStore([_negative()])
        result = GetFewShotNegativesUseCase(store).execute(
            workspace_id="w1", artifact_type="newsletter"
        )
        assert "REVIEWER FEEDBACK" in result
        assert "unsupported_figure, off_voice" in result
        assert "The 100-kids figure isn't in the source facts." in result

    def test_queries_store_with_workspace_type_and_cap(self):
        store = _RecordingStore([_negative()])
        GetFewShotNegativesUseCase(store).execute(
            workspace_id="w1", artifact_type="newsletter"
        )
        assert store.calls == [
            {
                "workspace_id": "w1",
                "artifact_type": "newsletter",
                "limit": cfg.FEEDBACK_FEW_SHOT_MAX,
            }
        ]

    def test_respects_max_cap(self, monkeypatch):
        monkeypatch.setattr(cfg, "FEEDBACK_FEW_SHOT_MAX", 2)
        many = [_negative(artifact_id=f"n{i}", case_id=f"newsletter:n{i}") for i in range(5)]
        store = _RecordingStore(many)
        result = GetFewShotNegativesUseCase(store).execute(
            workspace_id="w1", artifact_type="newsletter"
        )
        # limit passed through == the cap ...
        assert store.calls[0]["limit"] == 2
        # ... and the rendered block has exactly 2 bullet lines.
        assert result.count("\n- ") == 2

    def test_truncates_note_to_max_chars(self, monkeypatch):
        monkeypatch.setattr(cfg, "FEEDBACK_FEW_SHOT_MAX_NOTE_CHARS", 20)
        long_note = "x" * 500
        store = _RecordingStore([_negative(feedback_note=long_note)])
        result = GetFewShotNegativesUseCase(store).execute(
            workspace_id="w1", artifact_type="newsletter"
        )
        # The full 500-char note never appears; the ellipsis marks truncation.
        assert long_note not in result
        assert "…" in result
        assert ("x" * 20) in result
        assert ("x" * 21) not in result

    def test_codes_only_when_note_blank(self):
        store = _RecordingStore([_negative(feedback_note="")])
        result = GetFewShotNegativesUseCase(store).execute(
            workspace_id="w1", artifact_type="newsletter"
        )
        assert "- [unsupported_figure, off_voice]" in result
