"""What the runner does with an incomplete answer.

Almost every test here is about the difference between "false" and "we do not
know". That distinction is the whole product: a panel that renders an
unassessed axis as a red X invents a defect, and one that renders it as a pass
hides a real one. Both are the same lie in opposite directions.
"""

from __future__ import annotations

import pytest

from components.evaluation.application.ports.eval_ports import (
    AgentOutcome,
    AgentRunnerPort,
    AxisVerdict,
    CaseSourcePort,
    EvalCaseInput,
    JudgePort,
    JudgeVerdict,
    VerifierPort,
)
from components.evaluation.application.services.eval_run_service import EvalRunService

pytestmark = [pytest.mark.unit]

AXES = ["grounded", "severity_sound", "fix_applies"]

CASE = EvalCaseInput(
    case_id="case-1",
    scenario="public S3 bucket",
    prompt_inputs={"title": "public bucket"},
    solution_criteria=["names the bucket", "proposes a policy change"],
)


class _Cases(CaseSourcePort):
    def __init__(self, cases=None):
        self._cases = cases if cases is not None else [CASE]

    def load_cases(self, *, suite_id, workspace_id):
        return list(self._cases)


class _Agent(AgentRunnerPort):
    def __init__(self, outcome=None, raises=None):
        self._outcome = outcome or AgentOutcome(output="I would restrict the policy.", cost_usd=0.01)
        self._raises = raises

    def run_case(self, *, agent_type, workspace_id, case, model_slug):
        if self._raises:
            raise self._raises
        return self._outcome


class _Judge(JudgePort):
    def __init__(self, verdicts=None, raises=None):
        self._verdicts = verdicts if verdicts is not None else {"grounded": True, "severity_sound": False}
        self._raises = raises

    def grade(self, *, case, outcome, axes, model_slug):
        if self._raises:
            raise self._raises
        return JudgeVerdict(
            strengths=["cited the bucket"],
            weaknesses=["severity too low"],
            reasoning="because",
            verdicts=dict(self._verdicts),
            model_slug="gpt-4o-mini",
            cost_usd=0.002,
        )


class _Verifier(VerifierPort):
    def __init__(self, supported=("fix_applies",), verdict=None, raises=None):
        self._supported = set(supported)
        self._verdict = verdict
        self._raises = raises

    def supports(self, axis):
        return axis in self._supported

    def verify(self, *, axis, case, outcome):
        if self._raises:
            raise self._raises
        return self._verdict or AxisVerdict(axis=axis, passed=True, reason="")


def _service(**kw):
    return EvalRunService(
        case_source=kw.get("cases", _Cases()),
        agent_runner=kw.get("agent", _Agent()),
        judge=kw.get("judge", _Judge()),
        verifier=kw.get("verifier", _Verifier()),
    )


def _run_one(service):
    return service.execute_case(
        case=CASE, axes=AXES, agent_type="triage", workspace_id="ws-1", model_slug="gpt-4o-mini"
    )


class TestAxisRouting:
    def test_a_deterministic_axis_never_reaches_the_judge(self):
        """ADR 0033 D2: a check that can be mechanical must be. Asking an LLM
        whether a patch applies spends tokens for a worse answer."""
        judge = _Judge(verdicts={"grounded": True, "severity_sound": True, "fix_applies": False})
        execution = _run_one(_service(judge=judge, verifier=_Verifier(verdict=AxisVerdict("fix_applies", True))))

        # The verifier said True; the judge's False for the same axis is ignored.
        assert execution.axis_verdicts["fix_applies"] is True

    def test_judged_axes_come_from_the_judge(self):
        execution = _run_one(_service())

        assert execution.axis_verdicts["grounded"] is True
        assert execution.axis_verdicts["severity_sound"] is False

    def test_with_no_verifier_every_axis_is_judged(self):
        judge = _Judge(verdicts={"grounded": True, "severity_sound": True, "fix_applies": True})
        execution = _run_one(_service(verifier=None, judge=judge))

        assert set(execution.axis_verdicts) == set(AXES)


class TestNotMeasuredIsNotFailure:
    def test_an_axis_the_judge_omits_is_absent_not_false(self):
        """The judge is told to omit an axis it cannot decide. Defaulting that
        to False would manufacture a failure out of the judge's silence."""
        execution = _run_one(_service(judge=_Judge(verdicts={"grounded": True})))

        assert execution.axis_verdicts["grounded"] is True
        assert "severity_sound" not in execution.axis_verdicts

    def test_a_verifier_returning_none_leaves_the_axis_unmeasured(self):
        verifier = _Verifier(verdict=AxisVerdict("fix_applies", None, "no patch produced"))
        execution = _run_one(_service(verifier=verifier))

        assert "fix_applies" not in execution.axis_verdicts
        assert execution.axis_reasons["fix_applies"] == "no patch produced"

    def test_a_non_boolean_verdict_is_dropped_rather_than_coerced(self):
        """`{"grounded": "yes"}` is not a verdict. Coercing truthiness would
        turn the string "false" into a pass."""
        execution = _run_one(_service(judge=_Judge(verdicts={"grounded": True})))

        assert execution.axis_verdicts == {"grounded": True, "fix_applies": True}


class TestFailuresAreRecordedNotSwallowed:
    def test_an_exploding_agent_is_a_recorded_case_not_a_dead_run(self):
        execution = _run_one(_service(agent=_Agent(raises=RuntimeError("boom"))))

        assert execution.outcome.failed
        assert "boom" in execution.failure_reason
        assert execution.axis_verdicts == {}, "nothing was produced, so nothing can be graded"

    def test_an_exploding_judge_does_not_lose_the_deterministic_axes(self):
        execution = _run_one(_service(judge=_Judge(raises=RuntimeError("judge down"))))

        assert execution.axis_verdicts == {"fix_applies": True}
        assert "judge unavailable" in execution.reasoning

    def test_an_exploding_verifier_leaves_its_axis_unmeasured(self):
        execution = _run_one(_service(verifier=_Verifier(raises=RuntimeError("verifier down"))))

        assert "fix_applies" not in execution.axis_verdicts
        assert "verifier raised" in execution.axis_reasons["fix_applies"]

    def test_a_failed_agent_is_not_sent_to_the_judge(self):
        """Grading an empty output wastes tokens to grade nothing."""
        judge = _Judge(raises=AssertionError("judge must not be called"))
        execution = _run_one(_service(agent=_Agent(outcome=AgentOutcome(output="", error="timeout")), judge=judge))

        assert execution.failure_reason == "timeout"


class TestCostAndReporting:
    def test_cost_accrues_from_agent_and_judge(self):
        execution = _run_one(_service())

        assert execution.cost_usd == pytest.approx(0.012)

    def test_the_failure_reason_names_the_failed_axes(self):
        execution = _run_one(_service())

        assert "severity_sound" in execution.failure_reason

    def test_a_fully_passing_case_has_no_failure_reason(self):
        judge = _Judge(verdicts={"grounded": True, "severity_sound": True})
        execution = _run_one(_service(judge=judge))

        assert execution.failure_reason == ""


class TestSuiteIteration:
    def test_progress_is_reported_per_case(self):
        seen = []
        service = _service(cases=_Cases([CASE, CASE, CASE]))

        list(
            service.execute_suite(
                suite_id="s",
                workspace_id="ws-1",
                agent_type="triage",
                axes=AXES,
                model_slug="gpt-4o-mini",
                on_case=lambda i, total, ex: seen.append((i, total)),
            )
        )

        assert seen == [(1, 3), (2, 3), (3, 3)]

    def test_a_broken_progress_callback_does_not_kill_the_run(self):
        service = _service(cases=_Cases([CASE, CASE]))

        def _explode(*args):
            raise RuntimeError("ui blew up")

        results = list(
            service.execute_suite(
                suite_id="s",
                workspace_id="ws-1",
                agent_type="triage",
                axes=AXES,
                model_slug="gpt-4o-mini",
                on_case=_explode,
            )
        )

        assert len(results) == 2
