"""Celery tasks for executing AI agents asynchronously."""

from __future__ import annotations

import logging
import os
from typing import Any

from celery import shared_task
from django.utils import timezone

from components.agents.infrastructure.services.actions_service import get_ai_action_service
from components.agents.infrastructure.services.agents_service import get_agent_service
from components.knowledge.application.providers.openai_breaker_provider import (
    OPENAI_CHAT_SLUG,
    OpenAIUnavailableError,
    openai_allow_request,
    record_openai_failure,
    record_openai_success,
)
from infrastructure.persistence.ai.agents.models import AgentExecution
from infrastructure.persistence.ai.models import AITeammateProfile

logger = logging.getLogger(__name__)

# Allow tuning execution timeouts without touching global Celery settings.
AGENT_SOFT_TIME_LIMIT = int(os.getenv("AGENT_TASK_SOFT_TIME_LIMIT", "120"))
AGENT_TIME_LIMIT = int(os.getenv("AGENT_TASK_TIME_LIMIT", str(AGENT_SOFT_TIME_LIMIT + 30)))


@shared_task(
    bind=True,
    soft_time_limit=AGENT_SOFT_TIME_LIMIT,
    time_limit=AGENT_TIME_LIMIT,
    name="infrastructure.ai.agents.tasks.run_agent_execution",
)
def run_agent_execution(self, execution_id: str) -> dict[str, Any]:
    """Run a stored agent execution in the background."""
    try:
        execution = AgentExecution.objects.select_related("agent").get(id=execution_id)
    except AgentExecution.DoesNotExist:
        logger.error("AgentExecution %s not found", execution_id)
        return {"success": False, "error": "execution_not_found"}

    # Idempotency guard (celery-tasks skill §2). acks_late means the broker can
    # redeliver this task on a worker crash/deploy; agent.execute() is an
    # expensive, non-idempotent LLM call. If the row is already terminal, or
    # already RUNNING under a *different* task_id (another worker has it), skip
    # re-running rather than double-spending tokens.
    incoming_task_id = self.request.id or ""
    if execution.status == AgentExecution.STATUS_COMPLETED:
        logger.info(
            "run_agent_execution skip already-completed execution_id=%s task_id=%s",
            execution_id,
            incoming_task_id,
        )
        return {
            "success": bool(getattr(execution, "success", True)),
            "execution_id": str(execution.id),
            "state": execution.state,
            "skipped": "already_completed",
        }
    if (
        execution.status == AgentExecution.STATUS_RUNNING
        and execution.task_id
        and incoming_task_id
        and execution.task_id != incoming_task_id
    ):
        logger.info(
            "run_agent_execution skip already-running execution_id=%s owner_task_id=%s incoming_task_id=%s",
            execution_id,
            execution.task_id,
            incoming_task_id,
        )
        return {
            "success": False,
            "execution_id": str(execution.id),
            "error": "execution_already_running",
            "skipped": "already_running",
        }

    task_id = self.request.id or execution.task_id or ""

    # Transition execution to running state before invoking the agent
    execution.task_id = task_id
    execution.status = AgentExecution.STATUS_RUNNING
    execution.progress = max(execution.progress, 5)
    execution.state = {"status": AgentExecution.STATUS_RUNNING, "updated_at": timezone.now().isoformat()}
    execution.updated_at = timezone.now()
    execution.save(update_fields=["task_id", "status", "progress", "state", "updated_at"])

    self.update_state(state="PROGRESS", meta={"progress": execution.progress})

    agent_service = get_agent_service()
    agent_id = str(execution.agent.agent_id)

    try:
        agent = agent_service.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} could not be instantiated")

        context = execution.state.get("context") if isinstance(execution.state, dict) else None
        performed_by_id = execution.triggered_by_id or str(execution.agent.user_id)

        # Gate the LLM call behind the OpenAI chat circuit breaker so a fleet of
        # agent executions fails fast when OpenAI is down instead of each one
        # hanging / exhausting retries against a dead endpoint (celery-tasks §3e).
        if not openai_allow_request(OPENAI_CHAT_SLUG):
            raise OpenAIUnavailableError(OPENAI_CHAT_SLUG)
        try:
            result = agent.execute(
                execution.query,
                execution=execution,
                task_id=task_id,
                performed_by=str(performed_by_id) if performed_by_id else None,
                context=context,
            )
        except Exception:
            record_openai_failure(OPENAI_CHAT_SLUG)
            raise
        record_openai_success(OPENAI_CHAT_SLUG)

        execution.refresh_from_db()
        success = bool(result.get("success", True))
        response = {
            "success": success,
            "execution_id": str(execution.id),
            "result": result.get("result"),
            "state": execution.state,
            "error": result.get("error"),
        }

        if not success:
            err = result.get("error")
            self.update_state(
                state="FAILURE",
                meta={
                    "error": err,
                    "exc_type": type(err).__name__ if err else "AgentError",
                    "exc_message": str(err) if err else "",
                },
            )

        return response

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Agent execution %s failed", execution_id)
        execution.status = AgentExecution.STATUS_FAILED
        execution.success = False
        execution.error_message = str(exc)
        execution.progress = 100
        execution.state = {
            "status": AgentExecution.STATUS_FAILED,
            "error": str(exc),
            "updated_at": timezone.now().isoformat(),
        }
        execution.updated_at = timezone.now()
        execution.save(update_fields=["status", "success", "error_message", "progress", "state", "updated_at"])
        try:
            agent_service.get_agent_memory_service(agent_id).add_agent_message(f"Agent run failed: {exc}")
        except Exception:  # pylint: disable=broad-except
            logger.debug("Unable to record failure in agent memory for %s", agent_id)
        self.update_state(
            state="FAILURE", meta={"error": str(exc), "exc_type": exc.__class__.__name__, "exc_message": repr(exc)}
        )
        return {"success": False, "error": str(exc), "execution_id": str(execution.id)}


@shared_task(
    name="infrastructure.ai.agents.tasks.run_ai_teammate_cycle",
    soft_time_limit=240,
    time_limit=300,
)
def run_ai_teammate_cycle(workspace_id: str, *, force: bool = False) -> dict[str, Any]:
    """Run the AI teammate automation cycle for a single workspace."""
    action_service = get_ai_action_service()

    from infrastructure.persistence.workspaces.models import Workspace  # Local import to avoid circular dependency

    try:
        workspace_queryset = getattr(Workspace, "_base_manager", None) or Workspace.objects
        workspace_obj = workspace_queryset.get(id=workspace_id)
    except Workspace.DoesNotExist:
        logger.warning("Workspace %s not found; skipping AI teammate run", workspace_id)
        return {"success": False, "error": "workspace_not_found"}

    if not workspace_obj.ai_teammate_enabled and not force:
        logger.info("AI teammate disabled for workspace %s; skipping", workspace_id)
        return {"success": True, "skipped": True, "reason": "workspace_disabled"}

    try:
        profile = action_service.get_teammate(workspace_id)
        if not profile:
            profile = action_service.ensure_teammate(workspace_obj)
        else:
            desired_enabled = workspace_obj.ai_teammate_enabled
            desired_status = AITeammateProfile.STATUS_ACTIVE if desired_enabled else AITeammateProfile.STATUS_DISABLED
            if profile.is_enabled != desired_enabled or profile.status != desired_status:
                profile.is_enabled = desired_enabled
                profile.status = desired_status
                profile.save(update_fields=["is_enabled", "status", "updated_at"])

        if not profile.is_enabled and not force:
            logger.info("AI teammate profile disabled for workspace %s; skipping", workspace_id)
            return {"success": True, "skipped": True, "reason": "teammate_disabled"}
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unable to prepare AI teammate for workspace %s: %s", workspace_id, exc)
        return {"success": False, "error": str(exc)}

    logger.info("[run_ai_teammate_cycle] workspace=%s status=%s", workspace_id, profile.status)

    # The detector cron is no longer routed through an agent class — the
    # legacy `OrchestratorAgent.run_detector_cycle` was retired in favour
    # of a plain service so the LangGraph-native `AiTeammateAgent` only
    # handles interactive chat. See `application/services/detector_cycle.py`.
    from components.agents.application.services.detector_cycle import (
        run_detector_cycle,
    )

    try:
        result = run_detector_cycle(
            workspace_id,
            extras={"trigger": "scheduled", "performed_by": str(profile.user_id)},
        )
        # SEE-205 — surface perceived-error findings on the same scheduled,
        # kill-switch-gated, per-workspace cycle. Skipped when the cycle was
        # halted; best-effort so a scan failure never fails the teammate run.
        if not (isinstance(result, dict) and result.get("halted")):
            try:
                from components.agents.infrastructure.services.perceived_error_scan import (
                    scan_workspace_for_perceived_errors,
                )

                perceived = scan_workspace_for_perceived_errors(workspace_id)
                if isinstance(result, dict):
                    result["perceived_error_findings"] = perceived
            except Exception:  # pylint: disable=broad-except
                logger.exception("perceived_error_scan failed for workspace %s", workspace_id)
        return {"success": True, "result": result}
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("AI teammate detector cycle failed for workspace %s: %s", workspace_id, exc)
        return {"success": False, "error": str(exc)}


@shared_task(
    name="infrastructure.ai.agents.tasks.schedule_ai_teammate_runs",
    soft_time_limit=240,
    time_limit=300,
)
def schedule_ai_teammate_runs() -> dict[str, Any]:
    """Fan-out task that enqueues teammate cycles for enabled workspaces."""
    action_service = get_ai_action_service()
    scheduled: list[str] = []

    for profile in action_service.iter_enabled_seeds():
        if not profile.workspace_id:
            continue
        logger.info("[schedule_ai_teammate_runs] queueing workspace=%s", profile.workspace_id)
        run_ai_teammate_cycle.delay(str(profile.workspace_id))
        scheduled.append(str(profile.workspace_id))

    return {"success": True, "scheduled": scheduled}


@shared_task(
    name="infrastructure.ai.agents.tasks.dispatch_finding_specialist",
    soft_time_limit=AGENT_SOFT_TIME_LIMIT * 3,
    time_limit=AGENT_TIME_LIMIT * 3,
)
def dispatch_finding_specialist(
    workspace_id: str,
    specialist: str,
    goal: str,
    agent_context: dict[str, Any] | None = None,
    performed_by: str | None = None,
) -> dict[str, Any]:
    """Run a finding-router specialist dispatch OUT of the detector cycle.

    The ``AiFindingRouterDetector`` used to invoke the specialist's deep run
    synchronously inside the detector cycle — a batch of findings (each an LLM
    advisor + grader call) blew the 30s per-detector timeout every cycle. The
    router now enqueues THIS task and returns instantly; the specialist runs
    here on the agent worker with a deep-run-sized time budget (3× the single
    agent-execution limit — a dispatch processes a batch of findings).

    Orchestrator routing is preserved: this reuses the cycle's own
    entitlement-gated delegator (``_delegate_to_agent``), so a specialist still
    cannot be reached in a workspace that hasn't enabled it.

    Idempotent under redelivery (celery-tasks skill §2): the router's cache
    lease dedupes enqueues, ``process_pending_finding`` re-checks triage status
    under a row lock, and an already-drained backlog makes a replay a no-op —
    a redelivered dispatch never double-comments or double-moves a card.
    """
    from components.agents.application.services.detector_cycle import _delegate_to_agent
    from components.agents.infrastructure.adapters.langchain.tools._finding_processing import (
        stamp_run_telemetry_on_findings,
    )
    from components.agents.infrastructure.services import finding_dispatch_service as fds
    from infrastructure.persistence.workspaces.models import Workspace

    workspace = Workspace.objects.all_objects().filter(id=workspace_id).first()
    if workspace is None:
        logger.error("dispatch_finding_specialist workspace not found workspace_id=%s", workspace_id)
        return {"success": False, "error": "workspace_not_found"}

    performer = performed_by or str(workspace.workspace_owner_id)
    logger.info(
        "dispatch_finding_specialist started workspace_id=%s specialist=%s",
        workspace_id,
        specialist,
    )
    dispatch_started_at = timezone.now()
    # Tell the operator's HUD this batch is being worked on RIGHT NOW. Without it a
    # finding shows QUEUED for the whole 10–30s deep run and the product looks idle
    # at the exact moment it is doing the work. Fail-safe — a progress stamp never
    # fails the dispatch it describes.
    fds.stamp_dispatch_in_flight(
        workspace_id,
        specialist,
        trigger=str((agent_context or {}).get("source") or "dispatch"),
        task_ids=(agent_context or {}).get("finding_task_ids"),
    )
    result = _delegate_to_agent(
        agent_type=specialist,
        query=goal,
        context=agent_context or {},
        performer_id=performer,
        workspace=workspace,
    )
    ok = bool((result or {}).get("success", True))

    # Task #58 — persist the run's telemetry onto the finding rows the
    # specialist just triaged. The deep run's final state (rubric verdicts,
    # critic scores, retries, budget trips) used to be dropped here; the
    # stamp runs AFTER the run completes (never racing the row-locked triage
    # writes) and is fail-safe — it can only add telemetry, never fail the
    # dispatch.
    stamped = stamp_run_telemetry_on_findings(
        workspace_id=workspace_id,
        specialist=specialist,
        since=dispatch_started_at,
        run_result=result or {},
    )

    logger.info(
        "dispatch_finding_specialist completed workspace_id=%s specialist=%s success=%s telemetry_stamped=%d",
        workspace_id,
        specialist,
        ok,
        stamped,
    )
    return {
        "success": ok,
        "specialist": specialist,
        "workspace_id": workspace_id,
        "telemetry_stamped": stamped,
    }


# ── HTTP-enqueued deep runs ──────────────────────────────────────────────
#
# ``deep/plan-and-run`` and ``deep/run-plan`` used to execute the WHOLE deep
# run (LLM planner + LangGraph execution — minutes of wall-clock) inside the
# request path, blocking the single daphne ASGI process past the k8s liveness
# timeout and getting the api pod killed (exit 137, observed twice in one
# verification pass). The endpoints now create the pending DeepRun row,
# enqueue one of these tasks, and return 202; the worker executes through the
# SAME metered service front door (kill switch + quota + telemetry + the
# DeepRunLog/WS stream are unchanged — clients already follow the run by
# ``plan_id`` over the ``agent_run`` stream / the runs snapshot endpoint).


def _skip_if_not_runnable(run, incoming_task_id: str, thread_id: str) -> dict[str, Any] | None:
    """Idempotency guard shared by the deep-run tasks (celery-tasks §2).

    The broker can redeliver a task (visibility timeout, worker crash/deploy)
    and a deep run is an expensive, non-idempotent batch of LLM calls:

    - terminal row (completed/failed) → replay is a no-op;
    - RUNNING under a *different* task id → another worker owns it, skip.

    Ownership is stamped into ``DeepRun.state['celery_task_id']`` (the runner
    only overwrites ``state`` at completion), so no schema change is needed.
    """
    from infrastructure.persistence.ai.agents.models import DeepRun

    if run is None:
        return None
    if run.status in (DeepRun.STATUS_COMPLETED, DeepRun.STATUS_FAILED):
        logger.info(
            "deep_run task skip terminal thread_id=%s status=%s task_id=%s",
            thread_id,
            run.status,
            incoming_task_id,
        )
        return {"success": run.status == DeepRun.STATUS_COMPLETED, "plan_id": thread_id, "skipped": run.status}
    owner_task_id = (run.state or {}).get("celery_task_id") if isinstance(run.state, dict) else None
    if (
        run.status == DeepRun.STATUS_RUNNING
        and owner_task_id
        and incoming_task_id
        and owner_task_id != incoming_task_id
    ):
        logger.info(
            "deep_run task skip already-running thread_id=%s owner_task_id=%s incoming_task_id=%s",
            thread_id,
            owner_task_id,
            incoming_task_id,
        )
        return {"success": False, "plan_id": thread_id, "skipped": "already_running"}
    return None


def _claim_deep_run(run, incoming_task_id: str) -> None:
    """Stamp this delivery's task id onto the run for the redelivery guard."""
    from infrastructure.persistence.ai.agents.models import DeepRun

    if run is None or not incoming_task_id:
        return
    state = dict(run.state) if isinstance(run.state, dict) else {}
    state["celery_task_id"] = incoming_task_id
    DeepRun.objects.filter(id=run.id).update(state=state)


def _mark_deep_run_failed(thread_id: str, error: str) -> None:
    """Land a failure that happened BEFORE the runner took over (planner LLM
    error, kill switch flipped between enqueue and execution, quota raced to
    exhaustion). The runner marks its own failures; this catches the rest so
    a run can never sit in ``pending`` forever after its task died."""
    from components.agents.infrastructure.gateways.deep.logging import log_deep_event
    from infrastructure.persistence.ai.agents.models import DeepRun

    updated = (
        DeepRun.objects.filter(thread_id=thread_id)
        .exclude(status=DeepRun.STATUS_COMPLETED)
        .update(status=DeepRun.STATUS_FAILED, last_error=error)
    )
    if updated:
        log_deep_event(thread_id, "run_failed", status=DeepRun.STATUS_FAILED, payload={"error": error})


@shared_task(
    bind=True,
    name="infrastructure.ai.agents.tasks.run_deep_plan_and_run",
    # Pin to the AI-teammate worker's queue. The global route table
    # (infrastructure/celery/routes.py) also routes the whole
    # `infrastructure.ai.agents.tasks.*` family there; the explicit pin is kept
    # as belt-and-suspenders (same pin-at-the-task pattern as
    # cloud_posture.run_prowler_scan_for_account).
    queue="ai_teammate",
    # A deep run is planner + a batch of agent tasks — same 3x budget as
    # dispatch_finding_specialist, env-tunable via AGENT_TASK_SOFT_TIME_LIMIT.
    soft_time_limit=AGENT_SOFT_TIME_LIMIT * 3,
    time_limit=AGENT_TIME_LIMIT * 3,
)
def run_deep_plan_and_run(
    self,
    *,
    goal: str,
    plan_id: str,
    agent_type: str,
    user_id: str,
    workspace_id: str,
    team_id: str | None = None,
    agent_config: dict[str, Any] | None = None,
    model_name: str | None = None,
    sync_to_kanban: bool = True,
    extra_context: dict[str, Any] | None = None,
    deep_pack: str | None = None,
) -> dict[str, Any]:
    """Execute an HTTP-enqueued one-shot deep plan+run (LLM plans, then runs)."""
    from components.agents.application.commands.deep_run_command import (
        DeepPlanAndRunCommand,
        DeepRunFailure,
    )
    from components.agents.application.service import AgentsService
    from infrastructure.persistence.ai.agents.models import DeepRun

    incoming_task_id = self.request.id or ""
    run = DeepRun.objects.filter(thread_id=plan_id).first()
    skipped = _skip_if_not_runnable(run, incoming_task_id, plan_id)
    if skipped is not None:
        return skipped
    _claim_deep_run(run, incoming_task_id)

    logger.info(
        "run_deep_plan_and_run started plan_id=%s workspace_id=%s task_id=%s",
        plan_id,
        workspace_id,
        incoming_task_id,
    )
    command = DeepPlanAndRunCommand(
        goal=goal,
        agent_type=agent_type,
        user_id=user_id,
        workspace_id=workspace_id,
        plan_id=plan_id,
        team_id=team_id,
        agent_config=agent_config or {},
        model_name=model_name,
        sync_to_kanban=sync_to_kanban,
        extra_context=extra_context,
        deep_pack=deep_pack,
    )
    try:
        # Same metered front door the endpoint used to call synchronously:
        # kill switch + quota re-check at execution time, record on success.
        result = AgentsService().deep_plan_and_run(command)
    except Exception as exc:
        logger.exception("run_deep_plan_and_run failed plan_id=%s workspace_id=%s", plan_id, workspace_id)
        _mark_deep_run_failed(plan_id, str(exc))
        return {"success": False, "plan_id": plan_id, "error": str(exc)}

    if isinstance(result, DeepRunFailure):
        _mark_deep_run_failed(plan_id, result.error)
        logger.info("run_deep_plan_and_run completed plan_id=%s success=False", plan_id)
        return {"success": False, "plan_id": plan_id, "error": result.error}
    logger.info("run_deep_plan_and_run completed plan_id=%s success=True", plan_id)
    return {"success": True, "plan_id": plan_id}


@shared_task(
    bind=True,
    name="infrastructure.ai.agents.tasks.run_deep_run_plan",
    # See run_deep_plan_and_run for the queue pin + time-limit rationale.
    queue="ai_teammate",
    soft_time_limit=AGENT_SOFT_TIME_LIMIT * 3,
    time_limit=AGENT_TIME_LIMIT * 3,
)
def run_deep_run_plan(
    self,
    *,
    raw_plan: dict[str, Any],
    agent_type: str,
    user_id: str,
    workspace_id: str,
    team_id: str | None = None,
    agent_config: dict[str, Any] | None = None,
    thread_id: str | None = None,
    sync_to_kanban: bool = True,
) -> dict[str, Any]:
    """Execute an HTTP-enqueued pre-built PlanSpec (already validated at the API)."""
    from components.agents.application.commands.deep_run_command import (
        DeepRunFailure,
        DeepRunPlanCommand,
    )
    from components.agents.application.service import AgentsService
    from components.agents.domain.value_objects.plan_schemas import PlanSpec
    from infrastructure.persistence.ai.agents.models import DeepRun

    plan_id = (raw_plan or {}).get("plan_id") or ""
    run_thread = thread_id or plan_id
    incoming_task_id = self.request.id or ""
    run = DeepRun.objects.filter(thread_id=run_thread).first()
    skipped = _skip_if_not_runnable(run, incoming_task_id, run_thread)
    if skipped is not None:
        return skipped
    _claim_deep_run(run, incoming_task_id)

    logger.info(
        "run_deep_run_plan started plan_id=%s workspace_id=%s task_id=%s",
        run_thread,
        workspace_id,
        incoming_task_id,
    )
    try:
        # Deserialization of the payload the controller already validated —
        # a failure here means the enqueue contract itself broke; fail loud.
        validated_plan = PlanSpec.model_validate(raw_plan)
        command = DeepRunPlanCommand(
            raw_plan=raw_plan,
            agent_type=agent_type,
            user_id=user_id,
            workspace_id=workspace_id,
            team_id=team_id,
            agent_config=agent_config or {},
            thread_id=run_thread,
            sync_to_kanban=sync_to_kanban,
        )
        result = AgentsService().deep_run_plan(command, validated_plan=validated_plan)
    except Exception as exc:
        logger.exception("run_deep_run_plan failed plan_id=%s workspace_id=%s", run_thread, workspace_id)
        _mark_deep_run_failed(run_thread, str(exc))
        return {"success": False, "plan_id": run_thread, "error": str(exc)}

    if isinstance(result, DeepRunFailure):
        _mark_deep_run_failed(run_thread, result.error)
        logger.info("run_deep_run_plan completed plan_id=%s success=False", run_thread)
        return {"success": False, "plan_id": run_thread, "error": result.error}
    logger.info("run_deep_run_plan completed plan_id=%s success=True", run_thread)
    return {"success": True, "plan_id": run_thread}


# ── Automatic: the fix a specialist just produced becomes its draft PR ────


@shared_task(
    name="infrastructure.ai.agents.tasks.auto_draft_pr_for_finding",
    soft_time_limit=AGENT_SOFT_TIME_LIMIT,
    time_limit=AGENT_TIME_LIMIT,
)
def auto_draft_pr_for_finding(
    workspace_id: str,
    task_id: str,
    performed_by: str,
    acting_agent: str = "",
) -> dict[str, Any]:
    """Open the draft PR for a finding a specialist has just triaged.

    The missing HAND-OFF. Triage stamped "suggested a code fix" and stopped; the
    PR only ever opened when an operator pressed DRAFT FIX PR
    (:func:`draft_fix_for_finding`). So a finding in a connected repository sat
    on the board reading FIX READY with no artifact behind it — the exact
    "detected, then nothing" gap the product exists to close.

    This is dispatched by ``process_pending_finding`` after its triage write
    commits, so it runs for EVERY specialist that produces a repo-target fix, not
    just the one a human happened to click.

    Deliberately thin: it re-reads the card and delegates to
    :func:`_open_draft_pr_for_finding` — the ONE draft-PR engine, with every
    guardrail (patch scope, ``validate_patch``, the per-repo open-PR throttle,
    the connection + repo allowlist, the agent's ``open_draft_pr`` capability)
    and every refusal still recorded on the card. Nothing here re-runs the
    specialist: a suggestion already exists, and re-advising would burn an LLM
    call to reach the same place.

    Idempotent: a card that already carries a ``draft_pr.url`` is a no-op, so a
    duplicate dispatch (retry, overlapping cycle) can never open a second PR.
    """
    from infrastructure.persistence.project.models import Task

    card = Task.objects.filter(id=task_id, workspace_id=workspace_id).first()
    if card is None:  # deleted between the triage write and this task
        logger.info("auto_draft_pr_for_finding card_gone workspace_id=%s task_id=%s", workspace_id, task_id)
        return {"success": False, "error": "finding_not_found"}

    meta = card.metadata or {}
    if (meta.get("payload") or {}).get("draft_pr", {}).get("url"):
        logger.info("auto_draft_pr_for_finding already_open workspace_id=%s task_id=%s", workspace_id, task_id)
        return {"success": True, "reason": "already_open"}

    # Attribution is the product: the board must show that the AGENT opened this
    # PR off its own triage, not that a human asked for it.
    _append_finding_provenance(
        task_id,
        actor=f"agent:{acting_agent or 'specialist'}",
        action="requested its own fix draft (automatic — a repo finding always gets a PR)",
    )

    outcome = _open_draft_pr_for_finding(
        workspace_id=workspace_id,
        task_id=task_id,
        performed_by=performed_by,
        metadata=meta,
        source_type=card.source_type or "",
    )
    logger.info(
        "auto_draft_pr_for_finding completed workspace_id=%s task_id=%s agent=%s outcome=%s",
        workspace_id,
        task_id,
        acting_agent,
        outcome.get("reason") or ("opened" if outcome.get("pr_url") else "no_pr"),
    )
    return {"success": True, "acting_agent": acting_agent, **outcome}


# ── On-demand: "draft a fix PR for THIS finding" ─────────────────────────


@shared_task(
    name="infrastructure.ai.agents.tasks.draft_fix_for_finding",
    soft_time_limit=AGENT_SOFT_TIME_LIMIT * 3,
    time_limit=AGENT_TIME_LIMIT * 3,
)
def draft_fix_for_finding(
    workspace_id: str,
    task_id: str,
    performed_by: str,
) -> dict[str, Any]:
    """Operator-triggered: triage ONE finding through the deep pipeline, then — only
    if every guardrail passes — open its draft PR.

    The third trigger onto the same engine (auto-on-detection, cadence, and this).
    It is a Celery task, never in-request: the deep pipeline is 10–30s of LLM calls
    and blocking daphne on it is the standing problem (#88) this must not extend.
    The endpoint returns 202 with the run handle and the finding flips to DRAFTING.

    Deterministic dispatch, not planner routing. The specialist is READ OFF THE CARD
    (``metadata.agent_type``, stamped by the board handler's per-source builder), so
    a new pillar is correct for free, and it is PINNED via ``worker_agent_type`` →
    ``execute_plan_once(force_worker_agent_type=…)``. Handing a known target to the
    LLM planner is a codified failure mode: it re-routes by keyword to an agent
    without the right tools, which then fabricates success silently (2026-07-19).

    Safety invariant — an unsafe patch never reaches a repository, and an
    unverified one never reaches it UNLABELED. The PR step is
    ``OpenDraftPrUseCase``, the ONE draft-PR engine: the hard preconditions
    (triaged, patch-scope enforcement, ``validate_patch``, the per-repo SAST
    open-PR throttle, the connection + repo allowlist, and the agent's
    ``open_draft_pr`` capability) still refuse and record WHY on the card. The
    grounded-verifier / confidence signals are LABELS, not gates: an ungrounded
    or low-confidence fix still opens its draft PR, title-prefixed [UNVERIFIED]
    with the named evidence gap in the body — the draft PR is the human review
    surface, so the label downgrades where the old gate withheld.
    """
    from components.agents.application.services.detector_cycle import _delegate_to_agent
    from components.agents.infrastructure.services import finding_dispatch_service as fds
    from infrastructure.persistence.project.models import Task
    from infrastructure.persistence.workspaces.models import Workspace

    workspace = Workspace.objects.all_objects().filter(id=workspace_id).first()
    if workspace is None:
        logger.error("draft_fix_for_finding workspace not found workspace_id=%s", workspace_id)
        return {"success": False, "error": "workspace_not_found"}

    card = Task.objects.filter(id=task_id, workspace_id=workspace_id).first()
    if card is None:
        logger.error("draft_fix_for_finding card not found workspace_id=%s task_id=%s", workspace_id, task_id)
        return {"success": False, "error": "finding_not_found"}

    meta = card.metadata or {}
    specialist = str(meta.get("agent_type") or "").strip()
    source_type = card.source_type or ""
    if not fds.is_routable(source_type, specialist):
        logger.info(
            "draft_fix_for_finding not_routable workspace_id=%s task_id=%s source_type=%s agent_type=%s",
            workspace_id,
            task_id,
            source_type,
            specialist,
        )
        return {"success": False, "error": "not_routable", "source_type": source_type}

    logger.info(
        "draft_fix_for_finding started workspace_id=%s task_id=%s specialist=%s performed_by=%s",
        workspace_id,
        task_id,
        specialist,
        performed_by,
    )
    fds.stamp_dispatch_in_flight(workspace_id, specialist, trigger="on_demand", task_ids=[task_id])
    # Every AI action is posted to the board as provenance — including the human ask
    # that started it, so the card records WHO requested the fix and when.
    _append_finding_provenance(task_id, actor=f"user:{performed_by}", action=f"requested a fix draft from {specialist}")

    # Re-run the specialist unless a suggestion already exists: a triaged card
    # whose outcome was NO FIX stays re-attemptable (the operator's retry runs a
    # fresh pass with fresh context instead of bouncing off "already handled").
    triage_stamp = meta.get("triage") or {}
    payload_stamp = meta.get("payload") or {}
    has_suggestion = triage_stamp.get("status") == "triaged" and (
        bool(triage_stamp.get("suggested")) or bool(str(payload_stamp.get("suggested_fix") or "").strip())
    )
    run_id = ""
    if not has_suggestion:
        # Full deep run so the operator gets the DeepRun record, the per-step
        # DeepRunLog trace, the LIVE RUN progress surface, telemetry/cost capture,
        # and the rubric/critic verification pass — the machinery already built.
        result = _delegate_to_agent(
            agent_type=specialist,
            query=fds.build_finding_goal(task_id, meta),
            context=fds.build_finding_agent_context(specialist, task_id, meta),
            performer_id=str(performed_by),
            workspace=workspace,
        )
        run_id = str((result or {}).get("thread_id") or (result or {}).get("plan_id") or "")
        if run_id:
            # An id only. Run DETAIL (prompts / tool IO) stays owner-only behind its
            # existing authz; nothing here widens that read.
            _append_finding_provenance(
                task_id, actor=f"agent:{specialist}", action="drafted a fix", extra={"run_id": run_id}
            )
        card.refresh_from_db()
        meta = card.metadata or {}

    outcome = _open_draft_pr_for_finding(
        workspace_id=workspace_id,
        task_id=task_id,
        performed_by=performed_by,
        metadata=meta,
        source_type=source_type,
    )
    logger.info(
        "draft_fix_for_finding completed workspace_id=%s task_id=%s specialist=%s outcome=%s",
        workspace_id,
        task_id,
        specialist,
        outcome.get("reason") or ("opened" if outcome.get("pr_url") else "no_pr"),
    )
    return {"success": True, "specialist": specialist, "run_id": run_id, **outcome}


def _open_draft_pr_for_finding(
    *, workspace_id: str, task_id: str, performed_by: str, metadata: dict, source_type: str = ""
) -> dict:
    """Run the ONE draft-PR engine for a freshly triaged finding, or record WHY not.

    Never raises: a blocked PR is a product state the operator must SEE (the whole
    point of this change), not an exception that disappears into a task log.
    """
    from components.integrations.application.ports.vcs_port import VcsApiError
    from components.integrations.application.providers.vcs_provider import get_open_draft_pr_use_case
    from components.integrations.application.use_cases.open_draft_pr_use_case import (
        DraftPrPreconditionError,
    )
    from components.shared_kernel.domain.triage import TARGET_REPO, remediation_target

    # The artifact must MATCH the remediation target: a finding with no linked
    # repository (public/unlinked container image, cloud resource) has nothing
    # to open a PR against — its artifact is the fix snippet/guidance already on
    # the card. A clean no-op, NOT a ``draft_pr_blocked`` stamp: "PR blocked" on
    # a finding that never had a PR path is exactly the misleading noise this
    # distinction removes. (The request path already refuses with
    # ``no_repo_target``; this guards the direct/cadence callers.)
    if source_type and remediation_target(source_type, metadata.get("payload") or {}) != TARGET_REPO:
        logger.info(
            "draft_fix_for_finding no_repo_target workspace_id=%s task_id=%s source_type=%s",
            workspace_id,
            task_id,
            source_type,
        )
        return {
            "pr_url": "",
            "reason": "no_repo_target",
            "message": (
                "This finding's remediation target is not a connected repository — the fix "
                "ships as guidance/a snippet on the finding, not a pull request."
            ),
        }
    triage = metadata.get("triage") or {}
    if triage.get("status") != "triaged":
        return _record_draft_pr_blocked(
            workspace_id, task_id, "finding_not_triaged", "The specialist did not produce a triaged fix."
        )
    # No ``needs_human`` gate here: an ungrounded/unverified fix still opens its
    # draft PR — labeled [UNVERIFIED] by the engine — because the draft PR is the
    # human review surface. The engine's hard preconditions (scope, validate_patch,
    # throttle, allowlist, capability) still refuse below.

    try:
        result = get_open_draft_pr_use_case().execute(
            workspace_id=str(workspace_id), task_id=str(task_id), performed_by=str(performed_by)
        )
    except DraftPrPreconditionError as exc:
        return _record_draft_pr_blocked(workspace_id, task_id, exc.reason, str(exc))
    except VcsApiError as exc:
        logger.exception("draft_fix_for_finding vcs error workspace_id=%s task_id=%s", workspace_id, task_id)
        return _record_draft_pr_blocked(workspace_id, task_id, "vcs_api_error", str(exc))

    # Success path already stamps payload.draft_pr + a provenance event + a card
    # comment + the HITL notification (record_draft_pr) — nothing to add here.
    return {"pr_url": result.url, "pr_repo": result.repo, "pr_created": result.created}


def _record_draft_pr_blocked(workspace_id: str, task_id: str, reason: str, message: str) -> dict:
    """Persist WHY no PR was opened onto the finding card + its provenance trail.

    Fail-safe: recording the reason can never fail the task — but losing it would
    leave the operator with a click that did nothing visible, which is the exact
    failure this whole change exists to remove.
    """
    _append_finding_provenance(
        task_id,
        actor="agent:code_fix",
        action=f"draft PR not opened ({reason})",
        patch={"draft_pr_blocked": {"reason": reason, "message": message, "at": timezone.now().isoformat()}},
        clear_dispatch=True,  # the run is over — stop showing DRAFTING
    )
    logger.info("draft_fix_for_finding blocked workspace_id=%s task_id=%s reason=%s", workspace_id, task_id, reason)
    return {"pr_url": "", "reason": reason, "message": message}


def _append_finding_provenance(task_id, *, actor: str, action: str, extra=None, patch=None, clear_dispatch=False):
    """Append one provenance event to a finding card (and optionally patch its metadata).

    ONE row-locked writer for every on-demand outcome — the operator's request, the
    run that produced a fix, and a refusal — instead of three copies of the same
    dance. Uses the same ``select_for_update(of=("self",))`` discipline as the triage
    write, so it never races an overlapping specialist run.

    Fail-safe: provenance can never fail the action it describes, but losing it would
    leave the operator with a click that did nothing visible — the exact failure this
    work removes — so it is logged loudly.
    """
    from django.db import transaction

    from infrastructure.persistence.project.models import Task

    at = timezone.now().isoformat()
    try:
        with transaction.atomic():
            locked = Task.objects.select_for_update(of=("self",)).filter(id=task_id).first()
            if locked is None:
                return
            meta = locked.metadata or {}
            if patch:
                meta.update(patch)
            if clear_dispatch:
                meta.pop("triage_dispatch", None)
            provenance = meta.get("provenance") or {"events": []}
            provenance.setdefault("events", [])
            provenance["events"].append({"actor": actor, "action": action, "at": at, **(extra or {})})
            provenance["last_handled_by"] = actor
            provenance["last_handled_at"] = at
            meta["provenance"] = provenance
            locked.metadata = meta
            locked.save(update_fields=["metadata", "updated_at"])
    except Exception:
        logger.exception("finding_provenance_append_failed task_id=%s actor=%s action=%s", task_id, actor, action)
