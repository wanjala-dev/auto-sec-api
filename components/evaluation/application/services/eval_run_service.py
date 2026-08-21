"""Execute a suite and record what happened (ADR 0033 P2).

The orchestration is deliberately dull: for each case, run the agent, check the
deterministic axes in code, judge the rest, write one result row. The care is
concentrated in three places where the obvious implementation lies.

**A missing verdict is NOT MEASURED, never a failure.** If an axis has no
verifier registered and the judge did not return it, the axis is absent from
``axis_verdicts``. It does not become ``False``. A panel that renders an
unassessed axis as a red X invents a defect, which is the same species of lie
as rendering an unscanned workspace as clean (#415).

**A case that blows up is recorded, not swallowed and not fatal.** One
exploding case must neither abort the run nor vanish from it: it is written
with its error and counted in the denominator, because a run that quietly drops
its failures reports a pass rate over the cases that happened to work.

**Cost accrues even on failure.** Tokens spent on a case that errored were
still spent, and a spend figure that only counts successes understates the bill.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from components.evaluation.application.ports.eval_ports import (
    AgentOutcome,
    AgentRunnerPort,
    AxisVerdict,
    CaseSourcePort,
    EvalCaseInput,
    JudgePort,
    VerifierPort,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaseExecution:
    """Everything one case produced, ready to persist."""

    case: EvalCaseInput
    outcome: AgentOutcome
    axis_verdicts: dict[str, bool]
    axis_reasons: dict[str, str]
    strengths: list[str]
    weaknesses: list[str]
    reasoning: str
    judge_model_slug: str
    cost_usd: float
    failure_reason: str


class EvalRunService:
    """Runs a suite. Framework-free: every dependency arrives as a port."""

    def __init__(
        self,
        *,
        case_source: CaseSourcePort,
        agent_runner: AgentRunnerPort,
        judge: JudgePort,
        verifier: VerifierPort | None = None,
    ) -> None:
        self._cases = case_source
        self._agent = agent_runner
        self._judge = judge
        self._verifier = verifier

    # ── axis routing ────────────────────────────────────────────────────────

    def _split_axes(self, axes: list[str]) -> tuple[list[str], list[str]]:
        """Deterministic axes first; whatever is left goes to the judge.

        Where a verifier exists it WINS. ADR 0033 D2: a check that can be
        mechanical must be mechanical — asking an LLM whether a patch applies
        spends tokens to get a less reliable answer than `git apply` gives for
        free.
        """
        if self._verifier is None:
            return [], list(axes)
        deterministic = [a for a in axes if self._verifier.supports(a)]
        judged = [a for a in axes if a not in deterministic]
        return deterministic, judged

    # ── one case ────────────────────────────────────────────────────────────

    def execute_case(
        self, *, case: EvalCaseInput, axes: list[str], agent_type: str, workspace_id: str, model_slug: str
    ) -> CaseExecution:
        verdicts: dict[str, bool] = {}
        reasons: dict[str, str] = {}
        cost = 0.0

        try:
            outcome = self._agent.run_case(
                agent_type=agent_type, workspace_id=workspace_id, case=case, model_slug=model_slug
            )
        except Exception as exc:
            # The agent itself failed. That is a legitimate result — an agent
            # that crashes on a case has failed that case — so it is recorded
            # rather than raised, and every axis stays NOT MEASURED because
            # nothing was produced to assess.
            logger.exception("eval_case_agent_failed case=%s", case.case_id)
            return CaseExecution(
                case=case,
                outcome=AgentOutcome(output="", error=str(exc)),
                axis_verdicts={},
                axis_reasons={},
                strengths=[],
                weaknesses=[],
                reasoning="",
                judge_model_slug="",
                cost_usd=0.0,
                failure_reason=f"agent raised: {exc}",
            )

        cost += outcome.cost_usd

        if outcome.failed:
            # The agent produced NOTHING — it returned an error rather than
            # raising one. Nothing may be graded from that, and this is the
            # exact shape that shipped a false PASS: the judge was already
            # skipped here, but the deterministic verifiers were not, and
            # `verify_no_fabricated_asset("")` finds no fabricated URN in an
            # empty string and so returns PASS. A case that never ran displayed
            # a green tick.
            #
            # Found by the live smoke test on 2026-08-21, where every one of
            # eight cases died on an invalid agent id and the panel reported
            # `no_fabricated_asset` PASSED for all of them.
            #
            # "The agent said nothing" is not evidence that it fabricated
            # nothing, and an absence of output must never satisfy an
            # absence-shaped check.
            return CaseExecution(
                case=case,
                outcome=outcome,
                axis_verdicts={},
                axis_reasons=dict.fromkeys(axes, "the agent produced no output, so this axis was not assessed"),
                strengths=[],
                weaknesses=[],
                reasoning="",
                judge_model_slug="",
                cost_usd=cost,
                failure_reason=outcome.error,
            )

        deterministic, judged = self._split_axes(axes)

        for axis in deterministic:
            try:
                verdict: AxisVerdict = self._verifier.verify(axis=axis, case=case, outcome=outcome)
            except Exception as exc:  # a verifier must be total; belt and braces
                logger.exception("eval_verifier_failed axis=%s case=%s", axis, case.case_id)
                verdict = AxisVerdict(axis=axis, passed=None, reason=f"verifier raised: {exc}")
            if verdict.passed is not None:
                verdicts[axis] = verdict.passed
            if verdict.reason:
                reasons[axis] = verdict.reason

        strengths: list[str] = []
        weaknesses: list[str] = []
        reasoning = ""
        judge_model = ""

        if judged and not outcome.failed:
            try:
                judged_result = self._judge.grade(case=case, outcome=outcome, axes=judged, model_slug=model_slug)
                strengths = list(judged_result.strengths)
                weaknesses = list(judged_result.weaknesses)
                reasoning = judged_result.reasoning
                judge_model = judged_result.model_slug
                cost += judged_result.cost_usd
                for axis in judged:
                    # Only axes the judge actually returned. A judge that omits
                    # an axis leaves it NOT MEASURED; defaulting to False would
                    # manufacture a failure out of the judge's silence.
                    if axis in judged_result.verdicts:
                        verdicts[axis] = bool(judged_result.verdicts[axis])
            except Exception as exc:
                logger.exception("eval_judge_failed case=%s", case.case_id)
                reasoning = f"judge unavailable: {exc}"

        failure_reason = outcome.error
        if not failure_reason:
            failed_axes = sorted(a for a, ok in verdicts.items() if ok is False)
            if failed_axes:
                failure_reason = "failed: " + ", ".join(failed_axes)

        return CaseExecution(
            case=case,
            outcome=outcome,
            axis_verdicts=verdicts,
            axis_reasons=reasons,
            strengths=strengths,
            weaknesses=weaknesses,
            reasoning=reasoning,
            judge_model_slug=judge_model,
            cost_usd=cost,
            failure_reason=failure_reason,
        )

    def timed_out_execution(self, *, case: EvalCaseInput, seconds: int) -> CaseExecution:
        """A case that outran its own time limit, as a recordable result.

        Recording the timeout matters more than it looks. If a case that hangs
        simply produced no row, the run would sit one case short of its total
        and never finalise — a whole suite left permanently "in progress" by one
        slow case. And the slow case itself would be invisible, when it is
        exactly the finding worth having.

        Every axis is left UNMEASURED. A timeout says nothing about whether the
        agent would have been right, and scoring it as a failure would invent a
        quality defect out of a latency one.
        """
        return CaseExecution(
            case=case,
            outcome=AgentOutcome(output="", error=f"timed out after {seconds}s"),
            axis_verdicts={},
            axis_reasons={},
            strengths=[],
            weaknesses=[],
            reasoning="",
            judge_model_slug="",
            cost_usd=0.0,
            failure_reason=(
                f"timed out after {seconds}s — no axis was graded, so this case is unmeasured rather than failed"
            ),
        )

    # There is deliberately NO `execute_suite` here.
    #
    # It existed, and it looped over every case in one call. That is the shape
    # the fan-out replaced: one Celery task iterating a whole suite is bounded
    # by `task_time_limit = 300`, which at ~10-30s per case caps a suite at
    # roughly 10-30 cases — below the 50 the field considers a minimum useful
    # golden set. Keeping the method as a convenience would leave the defect one
    # import away from returning, and the next caller would have no way to know
    # it was the thing that got removed. A case at a time is the only unit of
    # work this service offers.


__all__ = ["CaseExecution", "EvalRunService"]
