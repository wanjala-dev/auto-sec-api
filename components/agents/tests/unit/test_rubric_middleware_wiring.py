"""Unit tests for the deepagents RubricMiddleware wiring (deep/rubric.py).

Covers the gating rules (settings/config/agent-type), the bounded-iterations
cap, and the grader's grounded-verifier tool. The middleware object itself is
only constructed when ``deepagents`` is importable; the gating logic tests run
regardless.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.deep import rubric as rubric_mod
from components.agents.infrastructure.adapters.langchain.deep.rubric import (
    MAX_ITERATIONS_CAP,
    RubricEvaluationCollector,
    build_grader_verifier_tool,
    drain_rubric_evaluations,
    rubric_middleware_enabled,
    rubric_run_metadata_update,
    summarize_rubric_evaluations,
)


def _evaluation(
    *,
    result="needs_revision",
    iteration=0,
    grading_run_id="run-1",
    explanation="Suggestion is generic.",
    criteria=None,
):
    """A ``RubricEvaluation`` exactly as deepagents 0.6.12 delivers it to
    ``on_evaluation``: a TypedDict (plain dict at runtime) with keys
    ``grading_run_id`` / ``iteration`` / ``result`` / ``explanation`` /
    ``criteria`` — NOT an object with ``verdict`` / ``feedback`` attributes.
    """
    return {
        "grading_run_id": grading_run_id,
        "iteration": iteration,
        "result": result,
        "explanation": explanation,
        "criteria": criteria
        if criteria is not None
        else [
            {"name": "names the symbol", "passed": False, "gap": "No module/symbol named."},
            {"name": "grounded cause", "passed": True},
        ],
    }


class TestGating:
    def test_disabled_by_default(self, settings):
        settings.DEEP_RUBRIC_MIDDLEWARE_ENABLED = False
        assert rubric_middleware_enabled({}) is False
        assert rubric_middleware_enabled(None) is False

    def test_global_setting_enables(self, settings):
        settings.DEEP_RUBRIC_MIDDLEWARE_ENABLED = True
        assert rubric_middleware_enabled({}) is True

    def test_agent_config_enables(self, settings):
        settings.DEEP_RUBRIC_MIDDLEWARE_ENABLED = False
        assert rubric_middleware_enabled({"rubric_middleware": True}) is True
        assert rubric_middleware_enabled({"rubric_middleware": {"max_iterations": 1}}) is True


def _fake_agent(agent_type="triage_agent", workspace_id="ws-1"):
    provider = SimpleNamespace(get_llm=lambda **kw: SimpleNamespace(kind="llm", **kw))
    agent = SimpleNamespace(
        config={"agent_type": agent_type},
        workspace_id=workspace_id,
        agent_id="agent-1",
        _resolve_llm_provider=lambda: provider,
    )
    return agent


class TestBuildRubricMiddleware:
    def test_none_for_non_critic_agent_type(self):
        mw = rubric_mod.build_rubric_middleware(agent=_fake_agent("workspace_agent"), config={})
        assert mw is None

    def test_builds_for_triage_agent_with_bounded_iterations(self):
        deepagents_rubric = pytest.importorskip("deepagents.middleware.rubric")
        mw = rubric_mod.build_rubric_middleware(
            agent=_fake_agent("triage_agent"),
            config={"max_iterations": 99},  # must be capped to <= 2
        )
        assert mw is not None
        assert isinstance(mw, deepagents_rubric.RubricMiddleware)
        max_iter = getattr(mw, "max_iterations", None)
        assert max_iter is not None and max_iter <= MAX_ITERATIONS_CAP

    def test_iterations_cap_constant_is_two(self):
        # The migration plan hard-requires max_iterations <= 2.
        assert MAX_ITERATIONS_CAP == 2


class TestGraderVerifierTool:
    def test_tool_name_is_stable(self):
        tool = build_grader_verifier_tool(_fake_agent())
        assert tool.name == "verify_suggestion_grounded"

    def test_no_task_id_reports_no_evidence(self):
        tool = build_grader_verifier_tool(_fake_agent())
        payload = json.loads(tool.func(suggestion_text="fix the ImportError in components.foo"))
        assert payload["grounded"] is None
        assert "No finding evidence" in payload["reason"]

    @pytest.mark.django_db
    def test_grounded_verdict_from_real_finding(self, workspace_factory, team_factory, user_factory):
        from infrastructure.persistence.project.models import Task

        pytest.importorskip("langchain_core")
        user = user_factory()
        workspace = workspace_factory()
        team = team_factory(workspace=workspace)
        # Minimal finding row: triage evidence names a concrete symbol.
        task = Task.objects.create(
            workspace=workspace,
            team=team,
            created_by=user,
            title="Triage: ImportError in AiEmbeddingsProvider",
            source_type="ai.log_watch",
            metadata={
                "payload": {
                    "message": "ImportError: cannot import name 'AiEmbeddingsProvider'",
                    "evidence": [{"detail": "AiEmbeddingsProvider raised ImportError"}],
                }
            },
        )
        agent = _fake_agent(workspace_id=str(workspace.id))
        agent.workspace_id = workspace.id

        tool = build_grader_verifier_tool(agent)
        grounded = json.loads(
            tool.func(
                suggestion_text="Fix the AiEmbeddingsProvider import in the knowledge factory.",
                task_id=str(task.id),
            )
        )
        assert grounded["grounded"] is True

        ungrounded = json.loads(
            tool.func(
                suggestion_text="Investigate further and monitor the logs for issues.",
                task_id=str(task.id),
            )
        )
        assert ungrounded["grounded"] is False
        assert ungrounded["reason"]


class TestEvaluationCollector:
    def test_records_real_typeddict_shape(self, caplog):
        import logging

        collector = RubricEvaluationCollector(grader_model="gpt-4o-mini", max_iterations=2)
        with caplog.at_level(logging.INFO, logger=rubric_mod.__name__):
            collector.record(_evaluation())
        drained = collector.drain()
        assert len(drained) == 1
        entry = drained[0]
        assert entry["result"] == "needs_revision"
        assert entry["iteration"] == 0
        assert entry["grading_run_id"] == "run-1"
        assert entry["explanation"] == "Suggestion is generic."
        assert entry["criteria"][0] == {
            "name": "names the symbol",
            "passed": False,
            "gap": "No module/symbol named.",
        }
        # The INFO line carries REAL values — the verdict=None regression
        # came from getattr() reads against this dict shape.
        record = next(r for r in caplog.records if "rubric_evaluation" in r.message)
        assert "verdict=needs_revision" in record.getMessage()
        assert "iteration=0" in record.getMessage()
        assert "run_id=run-1" in record.getMessage()
        assert "verdict=None" not in record.getMessage()

    def test_drain_clears(self):
        collector = RubricEvaluationCollector(grader_model="gpt-4o-mini", max_iterations=2)
        collector.record(_evaluation())
        assert len(collector.drain()) == 1
        assert collector.drain() == []

    def test_fail_safe_on_garbage(self, caplog):
        import logging

        class Broken:
            def __getattr__(self, name):
                raise RuntimeError("boom")

        collector = RubricEvaluationCollector(grader_model="gpt-4o-mini", max_iterations=2)
        with caplog.at_level(logging.WARNING, logger=rubric_mod.__name__):
            collector.record(Broken())  # must not raise
        assert collector.drain() == []
        assert any("rubric evaluation capture failed" in r.message for r in caplog.records)


class TestSummarizeRubricEvaluations:
    def test_satisfied_after_revision(self):
        evaluations = [
            _evaluation(result="needs_revision", iteration=0),
            _evaluation(result="satisfied", iteration=1, explanation="All criteria pass.", criteria=[]),
        ]
        stamp = summarize_rubric_evaluations(evaluations, max_iterations=2, grader_model="gpt-4o-mini")
        assert stamp["verdict"] == "satisfied"
        assert stamp["iterations"] == 2
        assert stamp["results"] == ["needs_revision", "satisfied"]
        assert stamp["feedback"] == "All criteria pass."
        assert stamp["grader"] == "gpt-4o-mini"
        assert stamp["source"] == "rubric_middleware"
        assert stamp["grading_run_id"] == "run-1"

    def test_max_iterations_reached_derived_like_the_middleware(self):
        # deepagents stamps `max_iterations_reached` only on the PRIVATE
        # `_rubric_status` (never on an evaluation); the summary re-derives
        # it from a terminal needs_revision + exhausted budget.
        evaluations = [
            _evaluation(result="needs_revision", iteration=0),
            _evaluation(result="needs_revision", iteration=1),
        ]
        stamp = summarize_rubric_evaluations(evaluations, max_iterations=2, grader_model="gpt-4o-mini")
        assert stamp["verdict"] == "max_iterations_reached"
        assert stamp["iterations"] == 2

    def test_non_terminal_needs_revision_is_reported_as_is(self):
        stamp = summarize_rubric_evaluations(
            [_evaluation(result="needs_revision", iteration=0)],
            max_iterations=2,
            grader_model="gpt-4o-mini",
        )
        assert stamp["verdict"] == "needs_revision"

    def test_grader_error(self):
        evaluations = [
            _evaluation(
                result="grader_error",
                explanation="Grader raised TimeoutError: ...",
                criteria=[],
            )
        ]
        stamp = summarize_rubric_evaluations(evaluations, max_iterations=2, grader_model="gpt-4o-mini")
        assert stamp["verdict"] == "grader_error"
        assert stamp["iterations"] == 1

    def test_feedback_includes_failing_gaps(self):
        stamp = summarize_rubric_evaluations([_evaluation()], max_iterations=2, grader_model="gpt-4o-mini")
        assert "Suggestion is generic." in stamp["feedback"]
        assert "names the symbol: No module/symbol named." in stamp["feedback"]

    def test_empty_is_none(self):
        assert summarize_rubric_evaluations([], max_iterations=2, grader_model="gpt-4o-mini") is None


class TestDrainRubricEvaluations:
    def test_drains_collector_payload(self):
        agent = _fake_agent()
        collector = RubricEvaluationCollector(grader_model="gpt-4o-mini", max_iterations=2)
        collector.record(_evaluation())
        agent._rubric_evaluation_collector = collector
        payload = drain_rubric_evaluations(agent)
        assert payload["max_iterations"] == 2
        assert payload["grader"] == "gpt-4o-mini"
        assert len(payload["evaluations"]) == 1
        # Drained — a second call has nothing to report.
        assert drain_rubric_evaluations(agent) is None

    def test_none_without_collector(self):
        assert drain_rubric_evaluations(_fake_agent()) is None

    def test_fail_safe_on_broken_collector(self, caplog):
        import logging

        class BrokenCollector:
            grader_model = "gpt-4o-mini"
            max_iterations = 2

            def drain(self):
                raise RuntimeError("boom")

        agent = _fake_agent()
        agent._rubric_evaluation_collector = BrokenCollector()
        with caplog.at_level(logging.WARNING, logger=rubric_mod.__name__):
            assert drain_rubric_evaluations(agent) is None
        assert any("rubric evaluation drain failed" in r.message for r in caplog.records)


class TestRubricRunMetadataStamp:
    def _response(self):
        return {
            "success": True,
            "result": "Fix the AiEmbeddingsProvider import.",
            "rubric_evaluations": {
                "evaluations": [
                    _evaluation(result="needs_revision", iteration=0),
                    _evaluation(result="satisfied", iteration=1, explanation="All pass.", criteria=[]),
                ],
                "max_iterations": 2,
                "grader": "gpt-4o-mini",
            },
        }

    def test_stamps_task_and_preserves_existing_metadata(self):
        state = {
            "run_metadata": {
                "total_input_tokens": 5,
                "rubric_verdicts": {"t0": {"verdict": "satisfied", "iterations": 1}},
            }
        }
        run_metadata = rubric_run_metadata_update(state=state, response=self._response(), task_id="t1")
        # Seeded from state: no clobbering of earlier tasks or token counts
        # (PlanState.run_metadata has no merge reducer).
        assert run_metadata["total_input_tokens"] == 5
        assert run_metadata["rubric_verdicts"]["t0"]["verdict"] == "satisfied"
        stamp = run_metadata["rubric_verdicts"]["t1"]
        assert stamp["verdict"] == "satisfied"
        assert stamp["iterations"] == 2
        assert stamp["grader"] == "gpt-4o-mini"
        assert stamp["source"] == "rubric_middleware"

    def test_none_when_response_has_no_evaluations(self):
        assert rubric_run_metadata_update(state={}, response={"success": True}, task_id="t1") is None
        assert rubric_run_metadata_update(state={}, response=None, task_id="t1") is None

    def test_fail_safe_on_malformed_payload(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger=rubric_mod.__name__):
            result = rubric_run_metadata_update(
                state={},
                response={"rubric_evaluations": {"evaluations": [{}], "max_iterations": "not-an-int"}},
                task_id="t1",
            )
        assert result is None
        assert any("rubric verdict stamping failed" in r.message for r in caplog.records)


class TestMiddlewareCallbackWiring:
    def test_on_evaluation_is_the_agent_collector(self):
        pytest.importorskip("deepagents.middleware.rubric")
        agent = _fake_agent("triage_agent")
        mw = rubric_mod.build_rubric_middleware(agent=agent, config={})
        assert mw is not None
        collector = getattr(agent, "_rubric_evaluation_collector", None)
        assert isinstance(collector, RubricEvaluationCollector)
        assert mw._on_evaluation == collector.record

    def test_end_to_end_callback_to_stamp(self):
        """Simulate the middleware firing on_evaluation per iteration (the
        real 0.6.12 delivery), then walk the full telemetry chain:
        callback -> drain -> response payload -> run_metadata stamp."""
        pytest.importorskip("deepagents.middleware.rubric")
        agent = _fake_agent("triage_agent")
        mw = rubric_mod.build_rubric_middleware(agent=agent, config={})
        assert mw is not None
        mw._on_evaluation(_evaluation(result="needs_revision", iteration=0))
        mw._on_evaluation(_evaluation(result="satisfied", iteration=1, explanation="All pass.", criteria=[]))

        payload = drain_rubric_evaluations(agent)
        assert payload is not None
        response = {"success": True, "result": "answer", "rubric_evaluations": payload}
        run_metadata = rubric_run_metadata_update(state={}, response=response, task_id="task-9")
        stamp = run_metadata["rubric_verdicts"]["task-9"]
        assert stamp == {
            "verdict": "satisfied",
            "iterations": 2,
            "feedback": "All pass.",
            "grader": "gpt-4o-mini",
            "source": "rubric_middleware",
            "grading_run_id": "run-1",
            "results": ["needs_revision", "satisfied"],
        }
