"""Integration tests for the Wave-4 prompt-eval reports API.

Verifies ``GET /ai/prompt-eval/reports/`` paginates JSON reports off
the configured directory and ``GET /ai/prompt-eval/reports/<file>/``
returns one report verbatim. Both reject path traversal via the
``filename`` segment.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _seed_report(directory: Path, name: str, *, prompt_id="planner.system",
                 version="v3", avg_score=8.4, case_count=15) -> Path:
    path = directory / name
    path.write_text(json.dumps({
        "_meta": {
            "prompt_id": prompt_id,
            "version": version,
            "label": "baseline",
            "created_at": "20260608-120000",
            "judge_provider": "openai",
        },
        "case_count": case_count,
        "average_score": avg_score,
        "pass_rate_at_seven": 0.86,
        "score_by_category": {"tone": avg_score, "completeness": avg_score},
        "results": [],
    }))
    return path


@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPT_EVAL_REPORTS_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.django_db
class TestPromptEvalReportsList:
    URL = "/ai/prompt-eval/reports/"

    def test_returns_401_when_unauthenticated(self, api_client, reports_dir):
        _seed_report(reports_dir, "planner-baseline-planner_system-v3-x.json")
        response = api_client.get(self.URL)
        assert response.status_code == 401

    def test_lists_reports_for_authenticated_user(
        self, api_client, user_factory, reports_dir,
    ):
        user = user_factory()
        api_client.force_authenticate(user=user)
        _seed_report(reports_dir, "planner-baseline-planner_system-v3-a.json")
        _seed_report(reports_dir, "planner-baseline-planner_system-v3-b.json")
        response = api_client.get(self.URL)
        assert response.status_code == 200
        body = response.data
        # DRF default pagination keys.
        assert body["count"] == 2
        first = body["results"][0]
        assert first["prompt_id"] == "planner.system"
        assert first["version"] == "v3"
        assert first["avg_score"] == 8.4
        assert first["filename"].endswith(".json")

    def test_filters_by_prompt_id_and_version(
        self, api_client, user_factory, reports_dir,
    ):
        user = user_factory()
        api_client.force_authenticate(user=user)
        _seed_report(reports_dir, "a.json", prompt_id="planner.system", version="v3")
        _seed_report(reports_dir, "b.json", prompt_id="planner.system", version="v2")
        _seed_report(reports_dir, "c.json", prompt_id="estimator.system", version="v2")

        response = api_client.get(self.URL, {"prompt_id": "planner.system"})
        assert response.status_code == 200
        ids = {r["filename"] for r in response.data["results"]}
        assert ids == {"a.json", "b.json"}

        response = api_client.get(self.URL, {
            "prompt_id": "planner.system",
            "version": "v3",
        })
        assert {r["filename"] for r in response.data["results"]} == {"a.json"}

    def test_empty_when_directory_missing(
        self, api_client, user_factory, monkeypatch, tmp_path,
    ):
        # Point at a non-existent directory; endpoint returns an empty
        # paginated body rather than 500.
        monkeypatch.setenv(
            "PROMPT_EVAL_REPORTS_DIR",
            str(tmp_path / "does-not-exist"),
        )
        user = user_factory()
        api_client.force_authenticate(user=user)
        response = api_client.get(self.URL)
        assert response.status_code == 200
        assert response.data["count"] == 0


@pytest.mark.django_db
class TestPromptEvalReportRetrieve:
    URL_TEMPLATE = "/ai/prompt-eval/reports/{name}/"

    def test_returns_full_report_json(
        self, api_client, user_factory, reports_dir,
    ):
        user = user_factory()
        api_client.force_authenticate(user=user)
        _seed_report(reports_dir, "demo.json", case_count=7)
        response = api_client.get(self.URL_TEMPLATE.format(name="demo.json"))
        assert response.status_code == 200
        assert response.data["case_count"] == 7
        assert response.data["_meta"]["prompt_id"] == "planner.system"

    def test_404_on_missing_file(self, api_client, user_factory, reports_dir):
        user = user_factory()
        api_client.force_authenticate(user=user)
        response = api_client.get(self.URL_TEMPLATE.format(name="missing.json"))
        assert response.status_code == 404

    def test_400_on_non_json_filename(
        self, api_client, user_factory, reports_dir,
    ):
        user = user_factory()
        api_client.force_authenticate(user=user)
        # Router matches up to the next `/`; passing something without a
        # `.json` suffix returns 400 (we reject anything not a *.json stem).
        response = api_client.get(self.URL_TEMPLATE.format(name="bogus"))
        assert response.status_code == 400


@pytest.mark.django_db
class TestPlannerJudgeProviderPlumbing:
    """Wave 4 added ``provider`` to PlannerJudge for cross-vendor grading."""

    def test_default_provider_is_none(self):
        from components.agents.tests.prompt_eval.graders.model.planner_judge import (
            PlannerJudge,
        )
        judge = PlannerJudge(model_name="gpt-4o-mini")
        assert judge._provider is None  # noqa: SLF001 — pin the contract.

    def test_provider_kwarg_round_trips(self):
        from components.agents.tests.prompt_eval.graders.model.planner_judge import (
            PlannerJudge,
        )
        judge = PlannerJudge(
            model_name="claude-sonnet-4-20250514",
            provider="anthropic",
        )
        assert judge._provider == "anthropic"

    def test_anthropic_is_a_registered_llmfactory_provider(self):
        from components.knowledge.infrastructure.factories.llms.factory import (
            LLMFactory,
        )
        assert "anthropic" in LLMFactory.PROVIDERS
        assert "llm" in LLMFactory.PROVIDERS["anthropic"]
