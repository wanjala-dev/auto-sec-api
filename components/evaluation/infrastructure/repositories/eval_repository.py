"""ORM access for evaluation (ADR 0033).

Every query here filters on ``workspace_id``. On the pooled tier that filter is
the tenant boundary — there is no database boundary behind it — so a method
that forgets it does not return slightly wrong data, it returns another
customer's quality evidence.
"""

from __future__ import annotations

from decimal import Decimal

from components.evaluation.application.ports.eval_ports import CaseSourcePort, EvalCaseInput
from components.evaluation.domain.value_objects.claim_tier import AxisEvidence


class DjangoEvalRepository(CaseSourcePort):
    # ── cases ───────────────────────────────────────────────────────────────

    def load_cases(self, *, suite_id: str, workspace_id: str) -> list[EvalCaseInput]:
        from infrastructure.persistence.evaluation.models import EvalCase

        rows = EvalCase.objects.filter(suite_id=suite_id, workspace_id=workspace_id).order_by("created_at")
        return [
            EvalCaseInput(
                case_id=str(row.id),
                scenario=row.scenario,
                prompt_inputs=row.prompt_inputs or {},
                solution_criteria=list(row.solution_criteria or []),
                label=row.label,
            )
            for row in rows
        ]

    # ── suites ──────────────────────────────────────────────────────────────

    def list_suites(self, *, workspace_id: str):
        from django.db.models import Count

        from infrastructure.persistence.evaluation.models import EvalSuite

        return (
            EvalSuite.objects.filter(workspace_id=workspace_id)
            .annotate(case_count=Count("cases"))
            .order_by("-created_at")
        )

    def get_suite(self, *, suite_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalSuite

        return EvalSuite.objects.filter(id=suite_id, workspace_id=workspace_id).first()

    def latest_run_for(self, *, suite_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalRun

        return EvalRun.objects.filter(suite_id=suite_id, workspace_id=workspace_id).order_by("-created_at").first()

    # ── runs ────────────────────────────────────────────────────────────────

    def create_run(self, *, workspace_id, suite, agent_type, model_slug, cases_total):
        from infrastructure.persistence.evaluation.models import EvalRun

        return EvalRun.objects.create(
            workspace_id=workspace_id,
            suite=suite,
            agent_type=agent_type,
            model_slug=model_slug,
            cases_total=cases_total,
            status=EvalRun.Status.PENDING,
        )

    def list_runs(self, *, workspace_id: str, limit: int = 25):
        from infrastructure.persistence.evaluation.models import EvalRun

        return EvalRun.objects.filter(workspace_id=workspace_id).select_related("suite").order_by("-created_at")[:limit]

    def get_run(self, *, run_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalRun

        return EvalRun.objects.filter(id=run_id, workspace_id=workspace_id).select_related("suite").first()

    def results_for(self, *, run_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalCaseResult

        return (
            EvalCaseResult.objects.filter(run_id=run_id, workspace_id=workspace_id)
            .select_related("case")
            .order_by("created_at")
        )

    def get_result(self, *, result_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalCaseResult

        return (
            EvalCaseResult.objects.filter(id=result_id, workspace_id=workspace_id)
            .select_related("run", "case", "deep_run")
            .first()
        )

    # ── writes during a run ─────────────────────────────────────────────────

    def record_result(self, *, run, execution) -> None:
        from infrastructure.persistence.evaluation.models import EvalCaseResult

        EvalCaseResult.objects.update_or_create(
            run=run,
            case_id=execution.case.case_id,
            defaults={
                "workspace_id": run.workspace_id,
                "axis_verdicts": execution.axis_verdicts,
                "judge_reasoning": execution.reasoning,
                "judge_strengths": execution.strengths,
                "judge_weaknesses": execution.weaknesses,
                "output": (execution.outcome.output or "")[:20000],
                "failure_reason": execution.failure_reason,
                "cost_usd": Decimal(str(round(execution.cost_usd, 6))),
                "deep_run_id": execution.outcome.deep_run_id,
            },
        )

    def mark_progress(self, *, run, completed: int, cost_usd: float) -> None:
        from infrastructure.persistence.evaluation.models import EvalRun

        EvalRun.objects.filter(pk=run.pk).update(
            cases_completed=completed,
            cost_usd=Decimal(str(round(cost_usd, 6))),
            status=EvalRun.Status.RUNNING,
        )

    # ── aggregation ─────────────────────────────────────────────────────────

    def axis_evidence(self, *, run_id: str, workspace_id: str, axes: list[str]) -> list[AxisEvidence]:
        """Per-axis passed/measured for a run.

        ``measured`` counts only results where the axis actually has a verdict.
        An axis nobody assessed must not inflate the denominator — that is how a
        suite reports a 40% pass rate when 60% of cases were never graded on
        that axis at all.
        """
        rows = self.results_for(run_id=run_id, workspace_id=workspace_id)
        tallies = {axis: [0, 0] for axis in axes}  # axis -> [passed, measured]
        for row in rows:
            verdicts = row.axis_verdicts or {}
            for axis in axes:
                if axis not in verdicts:
                    continue
                tallies[axis][1] += 1
                if bool(verdicts[axis]):
                    tallies[axis][0] += 1
        return [
            AxisEvidence(axis=axis, passed=passed, measured=measured) for axis, (passed, measured) in tallies.items()
        ]


__all__ = ["DjangoEvalRepository"]
