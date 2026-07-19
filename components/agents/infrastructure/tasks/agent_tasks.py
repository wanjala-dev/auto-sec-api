"""Celery tasks for executing AI agents asynchronously."""

from __future__ import annotations

import logging
import os
from typing import Any

from celery import shared_task
from django.utils import timezone

from components.agents.infrastructure.services.actions_service import get_ai_action_service
from components.agents.infrastructure.services.agents_service import get_agent_service
from components.knowledge.infrastructure.factories.openai_breaker import (
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
    result = _delegate_to_agent(
        agent_type=specialist,
        query=goal,
        context=agent_context or {},
        performer_id=performer,
        workspace=workspace,
    )
    ok = bool((result or {}).get("success", True))
    logger.info(
        "dispatch_finding_specialist completed workspace_id=%s specialist=%s success=%s",
        workspace_id,
        specialist,
        ok,
    )
    return {"success": ok, "specialist": specialist, "workspace_id": workspace_id}
