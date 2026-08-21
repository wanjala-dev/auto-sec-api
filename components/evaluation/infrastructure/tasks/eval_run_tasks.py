"""Run a suite in the background, reporting progress as it goes (ADR 0033 P2).

A 50-case run takes minutes. Surfacing nothing until the end looks hung, and an
operator who cannot tell "working" from "stuck" reaches for the refresh button
and starts a second run. So progress is written per case, through the existing
``BackgroundJob`` primitive rather than a second progress mechanism.

The run is bounded by the cost cap checked at dispatch AND re-checked here
against actual spend: an estimate is not a guarantee, and a run that overruns
its cap must stop rather than finish expensively and apologise.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="evaluation.run_eval_suite", bind=True, ignore_result=True)
def run_eval_suite(self, run_id: str) -> dict:
    """Execute one ``EvalRun``. Idempotent-ish: a completed run is not re-run."""
    from django.utils import timezone

    from components.evaluation.application.services.eval_run_service import EvalRunService
    from components.evaluation.infrastructure.adapters.eval_agent_runner_adapter import (
        EvalAgentRunnerAdapter,
    )
    from components.evaluation.infrastructure.adapters.llm_judge_adapter import LlmJudgeAdapter
    from components.evaluation.infrastructure.adapters.verifier_adapter import (
        DeterministicVerifierAdapter,
    )
    from components.evaluation.infrastructure.repositories.eval_repository import (
        DjangoEvalRepository,
    )
    from infrastructure.persistence.evaluation.models import EvalRun

    logger.info("run_eval_suite started run_id=%s task_id=%s", run_id, self.request.id)

    run = EvalRun.objects.select_related("suite").filter(id=run_id).first()
    if run is None:
        logger.error("run_eval_suite missing run_id=%s", run_id)
        return {"success": False, "error": "run not found"}

    if run.status in (EvalRun.Status.COMPLETED, EvalRun.Status.CANCELLED):
        # Re-delivery of a task whose run already finished. Returning quietly
        # is right; re-running would double the spend and overwrite results.
        logger.info("run_eval_suite already finished run_id=%s status=%s", run_id, run.status)
        return {"success": True, "skipped": run.status}

    repo = DjangoEvalRepository()
    service = EvalRunService(
        case_source=repo,
        agent_runner=EvalAgentRunnerAdapter(),
        judge=LlmJudgeAdapter(model_slug=run.model_slug),
        verifier=DeterministicVerifierAdapter(workspace_id=run.workspace_id),
    )

    run.status = EvalRun.Status.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])
    _job_phase(run, "running", 0)

    axes = list(run.suite.axes or [])
    spent = 0.0
    completed = 0

    try:
        for execution in service.execute_suite(
            suite_id=str(run.suite_id),
            workspace_id=str(run.workspace_id),
            agent_type=run.agent_type,
            axes=axes,
            model_slug=run.model_slug,
        ):
            repo.record_result(run=run, execution=execution)
            completed += 1
            spent += execution.cost_usd
            repo.mark_progress(run=run, completed=completed, cost_usd=spent)
            _job_phase(run, f"case {completed}/{run.cases_total}", completed)

            cap = _cap_for(run)
            if cap is not None and Decimal(str(spent)) > cap:
                # Stop and SAY SO. Silently truncating would report a pass rate
                # over a partial suite as though it covered everything.
                run.status = EvalRun.Status.FAILED
                run.last_error = (
                    f"stopped after {completed} of {run.cases_total} cases — spend "
                    f"${spent:.4f} exceeded the workspace cap of ${cap:.2f}"
                )
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "last_error", "finished_at"])
                _job_phase(run, "cap exceeded", completed, failed=True)
                logger.warning("run_eval_suite cap_exceeded run_id=%s spent=%s", run_id, spent)
                return {"success": False, "error": run.last_error}
    except Exception as exc:
        logger.exception("run_eval_suite failed run_id=%s", run_id)
        run.status = EvalRun.Status.FAILED
        run.last_error = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "last_error", "finished_at"])
        _job_phase(run, "failed", completed, failed=True)
        return {"success": False, "error": str(exc)}

    run.status = EvalRun.Status.COMPLETED
    run.finished_at = timezone.now()
    run.cases_completed = completed
    run.cost_usd = Decimal(str(round(spent, 6)))
    run.save(update_fields=["status", "finished_at", "cases_completed", "cost_usd"])
    _job_phase(run, "completed", completed, done=True)

    logger.info(
        "run_eval_suite completed run_id=%s cases=%s cost=%.4f task_id=%s",
        run_id,
        completed,
        spent,
        self.request.id,
    )
    return {"success": True, "cases": completed, "cost_usd": float(spent)}


def _cap_for(run) -> Decimal | None:
    """The workspace's AI cost cap, if one is configured."""
    try:
        cap = (getattr(run.workspace, "ai_config", None) or {}).get("eval_cost_cap_usd")
        return Decimal(str(cap)) if cap else None
    except Exception:
        return None


def _job_phase(run, phase: str, completed: int, *, failed: bool = False, done: bool = False) -> None:
    """Mirror progress onto the BackgroundJob the HUD already renders."""
    if not run.background_job_id:
        return
    try:
        from infrastructure.persistence.core.models import BackgroundJob

        fields = {"phase": phase}
        if run.cases_total:
            fields["progress"] = int(100 * completed / run.cases_total)
        if failed:
            fields["status"] = BackgroundJob.Status.FAILED
        elif done:
            fields["status"] = BackgroundJob.Status.SUCCEEDED
        else:
            fields["status"] = BackgroundJob.Status.RUNNING
        BackgroundJob.objects.filter(pk=run.background_job_id).update(**fields)
    except Exception:
        # Progress reporting must never take down a run.
        logger.exception("eval_background_job_update_failed run_id=%s", run.id)


__all__ = ["run_eval_suite"]
