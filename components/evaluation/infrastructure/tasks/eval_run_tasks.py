"""Run a suite as a FAN-OUT of per-case tasks (ADR 0033 D12).

This replaces a single task that looped over every case. That shape worked, and
it worked only because the curated suite has eight cases.

    task_time_limit      = 300   # hard kill
    task_soft_time_limit = 270

A case is an agent call plus a judge call, roughly 10-30 seconds with tool use.
Five minutes is therefore about 10-30 cases, and the field's own sizing guidance
puts a *minimum* useful golden set at 50 and a production one at 200-500. The
old shape was killed mid-run by the first realistic suite anyone would build.
It was not slow, it was structurally bounded at the wrong number.

So the unit of work is now ONE CASE:

* Each ``run_eval_case`` finishes far inside the limit. Suite size stops mattering.
* Cases run concurrently, so wall-clock is suite/concurrency, not suite x latency.
* Progress is durable per case, which makes a run RESUMABLE: a retry executes
  only the cases with no result row yet, instead of paying again for the ones
  already graded.
* The coordinator is short-lived — it dispatches and returns.

Three things this shape must get right, all of them consequences of concurrency:

**Counters are atomic.** See ``DjangoEvalRepository.accrue``. Two workers
finishing together must not both read 40 and both write 41.

**Finalisation happens exactly once**, claimed with a conditional UPDATE, because
several workers can see "this was the last case" at the same instant.

**Somebody watches for silence.** A fan-out can lose its dispatched tasks and
leave a run at RUNNING for ever. ``reap_stalled_eval_runs`` is what notices; a
run that stops making progress is FAILED and says so, rather than displaying a
frozen progress bar that reads as "still working".
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from celery import shared_task

logger = logging.getLogger(__name__)

#: Cases run on the agent worker's queue — it is the deployment already sized
#: for agent execution and already holding the credentials the tools need.
#: Naming a NEW queue would need a new worker in auto-sec-infra, and a queue
#: nothing consumes black-holes its tasks (see infrastructure/celery/routes.py).
EVAL_QUEUE = "ai_teammate"

#: Bounds how fast a large suite is pulled off the queue. Without it a 500-case
#: run would saturate the agent worker and starve the teammate cycle, which is
#: the product's actual loop — and would earn provider 429s on the way.
EVAL_CASE_RATE_LIMIT = "30/m"

#: A run that has recorded nothing for this long has lost its workers.
STALL_AFTER = timedelta(minutes=30)


@shared_task(name="evaluation.run_eval_suite", bind=True, ignore_result=True)
def run_eval_suite(self, run_id: str) -> dict:
    """Dispatch one task per outstanding case. Returns immediately."""
    from components.evaluation.infrastructure.repositories.eval_repository import DjangoEvalRepository
    from infrastructure.persistence.evaluation.models import EvalRun

    logger.info("run_eval_suite dispatch run_id=%s task_id=%s", run_id, self.request.id)

    run = EvalRun.objects.select_related("suite").filter(id=run_id).first()
    if run is None:
        logger.error("run_eval_suite missing run_id=%s", run_id)
        return {"success": False, "error": "run not found"}

    if run.status in (EvalRun.Status.COMPLETED, EvalRun.Status.CANCELLED):
        # Re-delivery of a task whose run already finished. Returning quietly is
        # right; re-dispatching would double the spend.
        logger.info("run_eval_suite already finished run_id=%s status=%s", run_id, run.status)
        return {"success": True, "skipped": run.status}

    repo = DjangoEvalRepository()
    pending = repo.pending_case_ids(run=run)

    if not pending:
        # Every case already has a result. This is the tail of a resumed run:
        # the work is done, only the finalisation was missed.
        _finalize(run_id=run_id, repo=repo)
        return {"success": True, "dispatched": 0, "note": "already complete"}

    repo.mark_running(run_id=run_id)
    _job_phase(run, f"0/{run.cases_total}", run.cases_completed)

    for case_id in pending:
        run_eval_case.apply_async(args=[str(run_id), case_id], queue=EVAL_QUEUE)

    logger.info("run_eval_suite dispatched run_id=%s cases=%s", run_id, len(pending))
    return {"success": True, "dispatched": len(pending)}


@shared_task(
    name="evaluation.run_eval_case",
    bind=True,
    ignore_result=True,
    queue=EVAL_QUEUE,
    rate_limit=EVAL_CASE_RATE_LIMIT,
    soft_time_limit=240,
    time_limit=270,
)
def run_eval_case(self, run_id: str, case_id: str) -> dict:
    """Grade ONE case, then decide whether the run is finished.

    Deliberately tolerant of re-delivery: the ``(run, case)`` unique constraint
    means a second execution overwrites its own result rather than creating a
    duplicate. What re-delivery WOULD do is double-count the cost, so the guard
    below skips a case that already has a result.
    """
    from celery.exceptions import SoftTimeLimitExceeded

    from components.evaluation.infrastructure.repositories.eval_repository import DjangoEvalRepository
    from infrastructure.persistence.evaluation.models import EvalCaseResult, EvalRun

    run = EvalRun.objects.select_related("suite").filter(id=run_id).first()
    if run is None:
        return {"success": False, "error": "run not found"}
    if run.status in (EvalRun.Status.COMPLETED, EvalRun.Status.CANCELLED, EvalRun.Status.FAILED):
        # The run was stopped (cap, cancel, reaper) after this case was queued.
        return {"success": True, "skipped": run.status}

    if EvalCaseResult.objects.filter(run_id=run_id, case_id=case_id).exists():
        # Already graded — a re-delivery. Not an error, and not a reason to
        # spend again.
        return {"success": True, "skipped": "already recorded"}

    repo = DjangoEvalRepository()

    cap = _cap_for(run)
    if cap is not None and repo.spend_so_far(run_id=run_id) > cap:
        # Concurrency means the cap is enforced with a small overshoot — cases
        # already in flight finish. Stopping the REST is what the cap is for,
        # and the message says how far it actually got.
        if repo.claim_terminal_state(
            run_id=run_id,
            status=EvalRun.Status.FAILED,
            last_error=(
                f"stopped after {run.cases_completed} of {run.cases_total} cases — spend exceeded "
                f"the workspace cap of ${cap:.2f}"
            ),
        ):
            _job_phase(run, "cap exceeded", run.cases_completed, failed=True)
            logger.warning("run_eval_case cap_exceeded run_id=%s", run_id)
        return {"success": False, "error": "cost cap exceeded"}

    case = repo.get_case_input(case_id=case_id, workspace_id=str(run.workspace_id))
    if case is None:
        logger.error("run_eval_case missing case run_id=%s case_id=%s", run_id, case_id)
        return {"success": False, "error": "case not found"}

    service = _service(run)
    axes = list(run.suite.axes or [])

    try:
        execution = service.execute_case(
            case=case,
            axes=axes,
            agent_type=run.agent_type,
            workspace_id=str(run.workspace_id),
            model_slug=run.model_slug,
        )
    except SoftTimeLimitExceeded:
        # A case that outran its own limit is a RECORDED failure, not a lost
        # one. Leaving no row would strand the run one case short of finishing
        # for ever, and would hide the slow case instead of naming it.
        logger.warning("run_eval_case timed out run_id=%s case_id=%s", run_id, case_id)
        execution = service.timed_out_execution(case=case, seconds=240)

    repo.record_result(run=run, execution=execution)
    completed, spent = repo.accrue(run_id=run_id, cost_usd=execution.cost_usd)
    _job_phase(run, f"case {completed}/{run.cases_total}", completed)

    if completed >= run.cases_total:
        _finalize(run_id=run_id, repo=repo)

    return {"success": True, "case_id": case_id, "completed": completed, "cost_usd": float(spent)}


@shared_task(name="evaluation.reap_stalled_eval_runs", ignore_result=True)
def reap_stalled_eval_runs() -> dict:
    """Fail runs that have gone quiet, so a dead run stops looking like a live one.

    The failure mode this exists for is specific to the fan-out: dispatched case
    tasks can be lost, and when they are, nothing remains to finish the run. It
    would otherwise sit at RUNNING with a half-filled progress bar indefinitely
    — which an operator reads as "still working", the most expensive possible
    misreading of "this died twenty minutes ago".
    """
    from django.utils import timezone

    from components.evaluation.infrastructure.repositories.eval_repository import DjangoEvalRepository
    from infrastructure.persistence.evaluation.models import EvalRun

    repo = DjangoEvalRepository()
    cutoff = timezone.now() - STALL_AFTER
    reaped = 0

    for run_id in repo.stalled_run_ids(older_than=cutoff):
        run = EvalRun.objects.filter(pk=run_id).first()
        if run is None:
            continue
        if repo.claim_terminal_state(
            run_id=run_id,
            status=EvalRun.Status.FAILED,
            last_error=(
                f"stalled after {run.cases_completed} of {run.cases_total} cases — no case has "
                f"reported for {int(STALL_AFTER.total_seconds() // 60)} minutes, so the remaining "
                "work was lost. Results already recorded are kept and remain valid."
            ),
        ):
            _job_phase(run, "stalled", run.cases_completed, failed=True)
            reaped += 1
            logger.warning("reap_stalled_eval_runs failed run_id=%s", run_id)

    if reaped:
        logger.info("reap_stalled_eval_runs reaped=%s", reaped)
    return {"reaped": reaped}


# ── helpers ─────────────────────────────────────────────────────────────────


def _service(run):
    """Assemble the runner for this run's MODE.

    Agent mode executes the real agent — tools, retrieval, its registry
    system prompt. Prompt mode executes the operator's typed prompt alone.
    Choosing here, from the suite, is what keeps the two from being mixed up
    by a caller that forgot which kind of suite it had.
    """
    from components.evaluation.application.services.eval_run_service import EvalRunService
    from components.evaluation.infrastructure.adapters.eval_agent_runner_adapter import EvalAgentRunnerAdapter
    from components.evaluation.infrastructure.adapters.llm_judge_adapter import LlmJudgeAdapter
    from components.evaluation.infrastructure.adapters.prompt_runner_adapter import PromptRunnerAdapter
    from components.evaluation.infrastructure.adapters.verifier_adapter import DeterministicVerifierAdapter
    from components.evaluation.infrastructure.repositories.eval_repository import DjangoEvalRepository
    from infrastructure.persistence.evaluation.models import EvalSuite

    if run.suite.mode == EvalSuite.Mode.PROMPT:
        runner = PromptRunnerAdapter(system_prompt=run.suite.system_prompt)
    else:
        runner = EvalAgentRunnerAdapter()

    return EvalRunService(
        case_source=DjangoEvalRepository(),
        agent_runner=runner,
        judge=LlmJudgeAdapter(model_slug=run.model_slug),
        verifier=DeterministicVerifierAdapter(workspace_id=run.workspace_id),
    )


def _finalize(*, run_id, repo) -> None:
    """Close the run — once, whoever gets there first."""
    from infrastructure.persistence.evaluation.models import EvalRun

    if not repo.claim_terminal_state(run_id=run_id, status=EvalRun.Status.COMPLETED):
        return  # another worker already closed it

    run = EvalRun.objects.filter(pk=run_id).first()
    if run is None:
        return
    _job_phase(run, "completed", run.cases_completed, done=True)
    logger.info(
        "run_eval_suite completed run_id=%s cases=%s cost=%s",
        run_id,
        run.cases_completed,
        run.cost_usd,
    )


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


__all__ = ["reap_stalled_eval_runs", "run_eval_case", "run_eval_suite"]
