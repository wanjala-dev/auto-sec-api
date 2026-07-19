"""Integration tests for ``DjangoEvalExampleRepository.list_recent_negatives`` (SEE-191).

Proves the few-shot lookup is workspace-scoped, decision-scoped
(CHANGES_REQUESTED / REJECTED only), artifact-type-scoped, newest-first, and
capped — the contract the reviewer-feedback injection relies on so one workspace
never sees another's feedback and positives don't leak in.
"""

from __future__ import annotations

import pytest

from components.agents.domain.value_objects.eval_example import (
    EvalExample,
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
        feedback_codes=["unsupported_figure"],
        feedback_note="fix the number",
        workspace_id="w1",
    )
    kwargs.update(overrides)
    return EvalExample(**kwargs)


@pytest.mark.integration
@pytest.mark.django_db
class TestListRecentNegatives:
    def test_scopes_to_workspace_type_and_negative_decisions(self):
        repo = DjangoEvalExampleRepository()
        # Target: two negatives for w1/newsletter.
        repo.add_example(_example(artifact_id="n1", case_id="newsletter:n1"))
        repo.add_example(
            _example(
                artifact_id="n2",
                case_id="newsletter:n2",
                feedback_decision=FeedbackDecision.REJECTED,
            )
        )
        # Noise that MUST be excluded:
        # - a positive override (approved_override)
        repo.add_example(
            _example(
                artifact_id="n3",
                case_id="newsletter:n3",
                feedback_decision=FeedbackDecision.APPROVED_OVERRIDE,
            )
        )
        # - another workspace
        repo.add_example(
            _example(artifact_id="n4", case_id="newsletter:n4", workspace_id="w2")
        )
        # - another artifact type (writing_draft, different dataset)
        repo.add_example(
            _example(
                dataset_name="feedback-writing_draft",
                artifact_type="writing_draft",
                artifact_id="d1",
                case_id="writing_draft:d1",
            )
        )

        results = repo.list_recent_negatives(
            workspace_id="w1", artifact_type="newsletter", limit=10
        )
        assert {e.artifact_id for e in results} == {"n1", "n2"}
        assert all(
            e.feedback_decision
            in (FeedbackDecision.CHANGES_REQUESTED, FeedbackDecision.REJECTED)
            for e in results
        )

    def test_newest_first_and_capped(self):
        from datetime import datetime, timedelta, timezone

        from infrastructure.persistence.prompt_eval.models import PromptEvalExample

        repo = DjangoEvalExampleRepository()
        for i in range(5):
            repo.add_example(
                _example(artifact_id=f"n{i}", case_id=f"newsletter:n{i}")
            )
        # created_at is auto_now_add; stamp distinct times so newest-first is
        # deterministic (a tight insert loop can tie on the DB clock). n4 newest.
        base = datetime(2026, 6, 1, tzinfo=timezone.utc)
        for i in range(5):
            PromptEvalExample.objects.filter(artifact_id=f"n{i}").update(
                created_at=base + timedelta(minutes=i)
            )

        results = repo.list_recent_negatives(
            workspace_id="w1", artifact_type="newsletter", limit=3
        )
        assert len(results) == 3
        assert [e.artifact_id for e in results] == ["n4", "n3", "n2"]

    def test_empty_workspace_returns_empty(self):
        repo = DjangoEvalExampleRepository()
        repo.add_example(_example())
        assert (
            repo.list_recent_negatives(
                workspace_id="", artifact_type="newsletter", limit=3
            )
            == []
        )

    def test_zero_limit_returns_empty(self):
        repo = DjangoEvalExampleRepository()
        repo.add_example(_example())
        assert (
            repo.list_recent_negatives(
                workspace_id="w1", artifact_type="newsletter", limit=0
            )
            == []
        )
