"""Unit tests for the verification loop (L2) — WorkerCritic + reflective_worker.

Pure unit: no DB, no real LLM. Covers the cheap deterministic gate (honesty
guard), the fail-safe degrade-to-passed, and the reflective wrapper's bounded
re-run / feedback-injection / passthrough / observability-stamp behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from components.agents.infrastructure.adapters.langchain.deep.critic import (
    CriticVerdict,
    WorkerCritic,
    reflective_worker,
)


class _StubCritic:
    """Deterministic critic: fails the first ``fail_n`` grades (confident, score
    3), then passes (score 8)."""

    def __init__(self, fail_n: int):
        self.fail_n = fail_n
        self.calls = 0

    def grade(self, *, task_title, task_description, answer, agent_type=None):
        self.calls += 1
        if self.calls <= self.fail_n:
            return CriticVerdict(passed=False, score=3, feedback="cite the evidence")
        return CriticVerdict(passed=True, score=8, feedback="")


class _ScriptedCritic:
    """Returns a scripted sequence of verdicts (for best-not-last / marginal)."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = 0

    def grade(self, *, task_title, task_description, answer, agent_type=None):
        v = self.verdicts[min(self.calls, len(self.verdicts) - 1)]
        self.calls += 1
        return v


def _task(agent_type="triage_agent"):
    return SimpleNamespace(id="t1", title="finding", description="an error", agent_type=agent_type)


def _worker_returning(summary):
    def base(state):
        return {"completed_tasks": [SimpleNamespace(summary=summary)], "artifacts": []}

    return base


def _atype(task):
    return getattr(task, "agent_type", "") or ""


class TestWorkerCriticGate:
    def test_honesty_guard_fails_without_llm(self):
        # A tool-failure summary is a definite fail — no LLM call.
        with mock.patch(
            "components.agents.infrastructure.adapters.langchain.deep.critic._is_agent_failure_summary",
            return_value=True,
        ):
            v = WorkerCritic().grade(task_title="t", task_description="d", answer="[FAILED — DID NOT PRODUCE DATA]")
        assert v.passed is False
        assert v.score == 0
        assert "tool" in v.feedback.lower()

    def test_llm_error_is_failsafe_pass(self):
        critic = WorkerCritic()
        with (
            mock.patch(
                "components.agents.infrastructure.adapters.langchain.deep.critic._is_agent_failure_summary",
                return_value=False,
            ),
            mock.patch.object(critic, "_get_llm", side_effect=RuntimeError("no key")),
        ):
            v = critic.grade(task_title="t", task_description="d", answer="a grounded answer")
        assert v.passed is True  # never block a run on critic failure

    def test_parse_low_score_is_fail(self):
        v = WorkerCritic._parse('{"passed": true, "score": 3, "feedback": "too vague"}')
        # passed=true but score below threshold → treated as fail.
        assert v.passed is False
        assert v.score == 3
        assert v.feedback == "too vague"

    def test_parse_high_score_pass(self):
        v = WorkerCritic._parse('{"passed": true, "score": 9, "feedback": ""}')
        assert v.passed is True


class TestReflectiveWorker:
    def test_passthrough_for_non_enabled_agent(self):
        critic = _StubCritic(fail_n=99)
        base = _worker_returning("whatever")
        wrapped = reflective_worker(
            base, critic, max_reflections=1, agent_type_of=_atype, enabled_agents={"triage_agent"}
        )
        wrapped({"task": _task(agent_type="workspace_agent")})
        assert critic.calls == 0  # non-enabled agent is never graded

    def test_reruns_once_on_fail_then_stops(self):
        critic = _StubCritic(fail_n=1)  # fail first grade, pass second
        runs = {"n": 0}

        def base(state):
            runs["n"] += 1
            return {"completed_tasks": [SimpleNamespace(summary=f"attempt {runs['n']}")], "artifacts": []}

        task = _task()
        wrapped = reflective_worker(base, critic, max_reflections=1, agent_type_of=_atype)
        result = wrapped({"task": task})

        assert runs["n"] == 2, "should re-run once after the failing grade"
        assert "Prior attempt feedback" in task.description
        assert "cite the evidence" in task.description
        scores = result["run_metadata"]["critic_scores"]["t1"]
        assert scores["reflections"] == 1
        # Every attempt is graded (including the re-run), best is tracked.
        assert scores["scores"] == [3, 8]
        assert scores["best_score"] == 8

    def test_stops_immediately_on_pass(self):
        critic = _StubCritic(fail_n=0)  # pass first grade
        runs = {"n": 0}

        def base(state):
            runs["n"] += 1
            return {"completed_tasks": [SimpleNamespace(summary="good")], "artifacts": []}

        wrapped = reflective_worker(base, critic, max_reflections=1, agent_type_of=_atype)
        wrapped({"task": _task()})
        assert runs["n"] == 1  # no re-run when the first grade passes

    def test_max_reflections_caps_reruns(self):
        critic = _StubCritic(fail_n=99)  # always fail
        runs = {"n": 0}

        def base(state):
            runs["n"] += 1
            return {"completed_tasks": [SimpleNamespace(summary="bad")], "artifacts": []}

        wrapped = reflective_worker(base, critic, max_reflections=2, agent_type_of=_atype)
        wrapped({"task": _task()})
        assert runs["n"] == 3  # 1 initial + 2 bounded re-runs, never more
        assert critic.calls == 3  # every attempt graded (incl. the final)

    def test_zero_reflections_is_noop(self):
        critic = _StubCritic(fail_n=99)
        base = _worker_returning("x")
        wrapped = reflective_worker(base, critic, max_reflections=0, agent_type_of=_atype)
        wrapped({"task": _task()})
        assert critic.calls == 0

    def test_marginal_fail_does_not_rerun(self):
        # A marginal fail (score 5, below pass=6 but above confident-floor=4)
        # must NOT trigger a re-run — reflection risks over-correcting it worse.
        critic = _ScriptedCritic([CriticVerdict(passed=False, score=5, feedback="tighten")])
        runs = {"n": 0}

        def base(state):
            runs["n"] += 1
            return {"completed_tasks": [SimpleNamespace(summary="marginal")], "artifacts": []}

        wrapped = reflective_worker(base, critic, max_reflections=1, agent_type_of=_atype)
        wrapped({"task": _task()})
        assert runs["n"] == 1  # no re-run on a marginal fail
        assert critic.calls == 1

    def test_returns_best_attempt_not_last(self):
        # Confident fail (3) triggers a re-run, but the re-run is WORSE (2). We
        # must return the FIRST attempt (the best), not the degraded re-run.
        critic = _ScriptedCritic(
            [
                CriticVerdict(passed=False, score=3, feedback="fix"),
                CriticVerdict(passed=False, score=2, feedback="still"),
            ]
        )
        seq = ["first-attempt", "worse-rerun"]
        runs = {"n": 0}

        def base(state):
            summary = seq[min(runs["n"], len(seq) - 1)]
            runs["n"] += 1
            return {"completed_tasks": [SimpleNamespace(summary=summary)], "artifacts": []}

        wrapped = reflective_worker(base, critic, max_reflections=1, agent_type_of=_atype)
        result = wrapped({"task": _task()})
        assert runs["n"] == 2  # it did re-run (confident fail)
        # ...but returned the BEST-scored (first) attempt, not the worse re-run.
        assert result["completed_tasks"][0].summary == "first-attempt"
        assert result["run_metadata"]["critic_scores"]["t1"]["best_score"] == 3
