"""
Adapters to bridge existing ReAct-style agents into deep-agent worker nodes.

These helpers intentionally stay thin: they wrap a single agent invocation and
return the structured delta expected by the orchestrator (completed_tasks,
artifacts). They do not enforce retries or budget control; upstream callers
should handle those concerns.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from django.utils import timezone

from components.agents.domain.value_objects.plan_schemas import ArtifactRef, PlanState, TaskSpec, WorkerResult
from components.agents.infrastructure.gateways.deep.logging import log_deep_event
from components.agents.infrastructure.services.agents_service import AgentService


def build_worker_from_agent(
    agent_type: str,
    user_id: str,
    workspace_id: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    run_context: Optional[Dict[str, Any]] = None,
    summarize_output: Optional[Callable[[Dict[str, Any]], str]] = None,
    deep_run_context: Optional[Any] = None,
) -> Callable[[PlanState], PlanState]:
    """
    Return a worker function that executes an existing agent and wraps the result.

    Args:
        agent_type: slug of the registered agent (e.g., "project_agent", "task_agent")
        user_id: owner of the agent
        workspace_id: workspace context for the agent
        config: optional overrides passed to AgentService.get_or_create_agent
        summarize_output: optional function to extract a concise summary from the
            agent execution response. Defaults to using "result" or repr(response).
        deep_run_context: optional DeepRunContext for in-tool log + progress
            emits. Accepted as a closure variable (NOT placed on
            ``run_context``) because LangGraph JSON-serialises ``run_context``
            on every checkpoint write, and a live ``DeepRunContext`` holds
            an observability adapter that can't round-trip through JSON.
            Captured here, attached to the per-call ``context`` dict that
            goes into ``service.execute_agent`` — that dict is request-
            local, never checkpointed.
    """

    service = AgentService()
    allowed_agents = None
    if isinstance(run_context, dict):
        allowed_agents = run_context.get("allowed_agents")
    if allowed_agents and agent_type not in allowed_agents:
        thread_id = run_context.get("run_id") if isinstance(run_context, dict) else None
        log_deep_event(
            thread_id,
            "worker_blocked",
            status="denied",
            agent_type=agent_type,
            payload={"reason": "agent_not_allowed"},
        )
        raise PermissionError(f"Agent type '{agent_type}' is not allowed for this run.")

    def _default_summary(response: Dict[str, Any]) -> str:
        if not response:
            return "No response returned from agent."
        for key in ("result", "detail", "message", "output"):
            if key in response and response[key]:
                return str(response[key])
        return str(response)

    summarizer = summarize_output or _default_summary

    def _build_worker_query(task: TaskSpec, state: PlanState) -> str:
        """Compose a structured prompt: title + description + acceptance + upstream artifacts.

        Workers were previously only seeing `task.title`, which dropped
        every detail the planner produced. We now include description,
        acceptance criteria, and short summaries of any artifacts produced
        by completed upstream tasks so the worker has real context.
        """
        lines: list[str] = [f"Task: {task.title}"]
        if getattr(task, "description", None):
            lines.append(f"Description: {task.description}")
        metadata = task.metadata or {}
        acceptance = metadata.get("acceptance_criteria") or metadata.get("acceptance")
        if acceptance:
            lines.append(f"Acceptance criteria: {acceptance}")

        # Surface summaries from upstream artifacts so dependent tasks can
        # build on prior work without re-doing it.
        upstream_summaries: list[str] = []
        completed = state.get("completed_tasks") or []
        for entry in completed:
            summary = getattr(entry, "summary", None) or (entry.get("summary") if isinstance(entry, dict) else None)
            if summary:
                upstream_summaries.append(str(summary))
        if upstream_summaries:
            joined = "\n- ".join(upstream_summaries[-5:])
            lines.append(f"Upstream task summaries:\n- {joined}")

        return "\n".join(lines)

    def worker(state: PlanState) -> PlanState:
        task: Optional[TaskSpec] = state.get("task") if state else None
        if not task:
            return {}

        thread_id = run_context.get("run_id") if isinstance(run_context, dict) else None
        department_id = run_context.get("department_id") if isinstance(run_context, dict) else None
        try:
            agent_record = service.get_or_create_agent(
                agent_type=agent_type,
                user_id=user_id,
                workspace_id=workspace_id,
                config=config or {},
                department_id=department_id,
            )
        except PermissionError as exc:
            log_deep_event(
                thread_id,
                "worker_blocked",
                status="denied",
                agent_type=agent_type,
                payload={"task_id": task.id, "error": str(exc)},
            )
            raise
        agent_id = str(agent_record.get("agent_id"))
        context = {
            "task": task.model_dump(),
            "plan_id": (state.get("plan").plan_id if state.get("plan") else None),
            "timestamp": timezone.now().isoformat(),
        }
        if run_context:
            context["run_context"] = run_context
        # Pull the closure-captured DeepRunContext (built by the runner,
        # NOT stashed on run_context — see the docstring) into the
        # request-local context dict that goes into the agent. The
        # context dict here is per-call; it never enters LangGraph
        # state and so is not checkpointed.
        if deep_run_context is not None:
            context["deep_run_context"] = deep_run_context
        log_deep_event(
            thread_id,
            "worker_started",
            status="running",
            agent_type=agent_type,
            payload={"task_id": task.id},
        )
        worker_query = _build_worker_query(task, state)
        try:
            response = service.execute_agent(
                agent_id=agent_id,
                query=worker_query,
                performed_by=user_id,
                context=context,
            )
        except Exception as exc:
            log_deep_event(
                thread_id,
                "worker_failed",
                status="failed",
                agent_type=agent_type,
                payload={"task_id": task.id, "error": str(exc)},
            )
            raise
        log_deep_event(
            thread_id,
            "worker_completed",
            status="completed",
            agent_type=agent_type,
            payload={"task_id": task.id},
        )

        summary = summarizer(response)
        worker_result = WorkerResult(
            task_id=task.id,
            summary=summary,
            artifact_refs=response.get("artifacts") or [],
            risks=[],
            next_inputs={},
        )

        artifacts = response.get("artifacts") or []
        parsed_artifacts = []
        for art in artifacts:
            try:
                parsed_artifacts.append(ArtifactRef(**art))
            except Exception:
                # Ignore artifacts that are not shape-compatible yet.
                continue

        return {
            "completed_tasks": [worker_result],
            "artifacts": parsed_artifacts,
        }

    return worker
