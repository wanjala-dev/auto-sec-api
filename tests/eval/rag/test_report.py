"""Unit tests for the report writer + aggregate computation.

These tests exercise the surfaces that should be deterministic:
JSON shape, HTML smoke render, aggregate math. The LLM-judged metrics
are tested in test_metrics.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.eval.rag.metrics import MetricResult
from tests.eval.rag.report import write_reports
from tests.eval.rag.scorer import ScoredEntry, ScoredRun


def _entry(
    *,
    prompt_id: str,
    category: str,
    faith: float,
    ans_rel: float,
    ctx_prec: float,
    ctx_rec: float,
    expected_specialist: str = "",
    routed_specialists: list[str] | None = None,
) -> ScoredEntry:
    return ScoredEntry(
        prompt_id=prompt_id,
        question=f"Q for {prompt_id}",
        category=category,
        expected_specialist=expected_specialist,
        routed_specialists=routed_specialists or [],
        answer=f"A for {prompt_id}",
        error="",
        metrics={
            "faithfulness": MetricResult(name="faithfulness", score=faith, detail={}),
            "answer_relevancy": MetricResult(name="answer_relevancy", score=ans_rel, detail={}),
            "context_precision": MetricResult(name="context_precision", score=ctx_prec, detail={}),
            "context_recall": MetricResult(name="context_recall", score=ctx_rec, detail={}),
        },
        retrieved_chunks_count=3,
    )


class TestAggregates:
    def test_mean_of_metrics(self):
        run = ScoredRun(
            run_id="t1",
            run_started_at="",
            workspace_uuid="",
            target="local",
            entries=[
                _entry(prompt_id="a", category="x", faith=1.0, ans_rel=1.0, ctx_prec=1.0, ctx_rec=1.0),
                _entry(prompt_id="b", category="x", faith=0.0, ans_rel=0.0, ctx_prec=0.0, ctx_rec=0.0),
            ],
        )
        agg = run.aggregates()
        assert agg["faithfulness"] == 0.5
        assert agg["answer_relevancy"] == 0.5
        assert agg["context_precision"] == 0.5
        assert agg["context_recall"] == 0.5

    def test_empty_run_returns_zeros_not_nan(self):
        run = ScoredRun(run_id="t1", run_started_at="", workspace_uuid="", target="local", entries=[])
        agg = run.aggregates()
        assert agg["faithfulness"] == 0.0
        # JSON-serializable; no NaN
        json.dumps(agg)

    def test_routing_accuracy_skips_empty_expected(self):
        """expected_specialist="" (multi-route / clarify) must not pull
        routing accuracy down. Only entries with a specific expected
        specialist contribute.
        """
        run = ScoredRun(
            run_id="t1", run_started_at="", workspace_uuid="", target="local",
            entries=[
                _entry(prompt_id="a", category="x", faith=1, ans_rel=1, ctx_prec=1, ctx_rec=1,
                       expected_specialist="user_agent", routed_specialists=["user_agent"]),
                _entry(prompt_id="b", category="x", faith=1, ans_rel=1, ctx_prec=1, ctx_rec=1,
                       expected_specialist="", routed_specialists=["user_agent", "donation_agent"]),
            ],
        )
        assert run.aggregates()["routing_accuracy"] == 1.0

    def test_routing_accuracy_counts_multi_route_hit(self):
        """A multi-route emit (3 tasks) counts as a hit if the
        expected specialist is anywhere in the routed list."""
        run = ScoredRun(
            run_id="t1", run_started_at="", workspace_uuid="", target="local",
            entries=[
                _entry(prompt_id="a", category="x", faith=1, ans_rel=1, ctx_prec=1, ctx_rec=1,
                       expected_specialist="user_agent",
                       routed_specialists=["user_agent", "donation_agent", "sponsorship_agent"]),
            ],
        )
        assert run.aggregates()["routing_accuracy"] == 1.0

    def test_routing_accuracy_partial(self):
        run = ScoredRun(
            run_id="t1", run_started_at="", workspace_uuid="", target="local",
            entries=[
                _entry(prompt_id="a", category="x", faith=1, ans_rel=1, ctx_prec=1, ctx_rec=1,
                       expected_specialist="user_agent", routed_specialists=["user_agent"]),
                _entry(prompt_id="b", category="x", faith=1, ans_rel=1, ctx_prec=1, ctx_rec=1,
                       expected_specialist="user_agent", routed_specialists=["donation_agent"]),
            ],
        )
        assert run.aggregates()["routing_accuracy"] == 0.5


class TestReportRender:
    def test_writes_json_and_html(self, tmp_path: Path):
        run = ScoredRun(
            run_id="render-test",
            run_started_at="2026-06-10T00:00:00",
            workspace_uuid="ws-uuid",
            target="local",
            entries=[
                _entry(prompt_id="a", category="identity",
                       faith=0.9, ans_rel=0.8, ctx_prec=1.0, ctx_rec=1.0,
                       expected_specialist="user_agent",
                       routed_specialists=["user_agent"]),
            ],
        )
        write_reports(scored=run, reports_dir=tmp_path)

        json_path = tmp_path / "scored-render-test.json"
        html_path = tmp_path / "scored-render-test.html"
        assert json_path.exists() and html_path.exists()

        data = json.loads(json_path.read_text())
        assert data["run_id"] == "render-test"
        assert data["aggregates"]["faithfulness"] == 0.9
        assert data["entries"][0]["prompt_id"] == "a"

        # HTML smoke: must contain the run id and the aggregate score.
        html_text = html_path.read_text()
        assert "render-test" in html_text
        assert "0.90" in html_text or "0.9" in html_text
        # Must include the question we set
        assert "Q for a" in html_text
