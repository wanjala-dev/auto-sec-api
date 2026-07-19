"""AI Teammate Agent — LangGraph-native replacement for the legacy
ReAct OrchestratorAgent (ADR 0003).

The legacy `OrchestratorAgent` was a 600-line ReAct class that mixed
chat, sub-agent delegation, and the detector cron in a single `execute`
method. It has been retired. This agent is a thin facade that:

- Routes interactive chat queries through the deep LangGraph pipeline
  (`deep.runner.execute_plan_once` via `AgentService._execute_deep`).
- Defers detector cron execution to
  `application.services.detector_cycle.run_detector_cycle`, which the
  Celery task `run_ai_teammate_cycle` now calls directly without going
  through this class at all.

This agent therefore exposes ZERO custom tools and ZERO ReAct loop. It
exists purely so the slugs `ai_teammate` / `orchestrator` / `planner`
remain registered and resolvable from `AgentRegistry`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
)
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)

logger = logging.getLogger(__name__)


@register_agent(
    "ai_teammate",
    aliases=("ai_teammate_agent", "orchestrator", "orchestrator_agent", "planner"),
)
class AiTeammateAgent(WorkspaceContextMixin, BaseAgent):
    """LangGraph-native orchestrator. No ReAct, no sub-agent tools."""

    profile = {
        "name": "AI Teammate",
        "summary": (
            "Plans and executes multi-step work through the LangGraph "
            "deep-agent pipeline. Delegates to domain agents (project, "
            "budget, sponsorship, …) as workers under a planner / "
            "scheduler / synthesizer graph."
        ),
        "capabilities": [
            "Plan work for a goal and execute it as a task DAG",
            "Delegate to domain agents as workers with policy gates",
            "Pause for human approval before risky actions",
            "Resume durably from checkpoints after failures",
            "Surface a final synthesised answer with goal-met check",
        ],
        "sample_prompts": [
            "Plan and run a fundraising review for this quarter.",
            "Create a project for the literacy drive and assign owners.",
            "Audit budgets and surface anything overspent.",
        ],
    }

    def _setup_tools(self):
        """No standalone tools — workers are agents, not tools."""
        self.tools = []

    def _create_agent_executor(self) -> None:
        """Skip the ReAct executor. Deep pipeline handles execution."""
        self.agent_executor = None

    def execute(
        self,
        query: str = "",
        *,
        execution=None,
        execution_id: int | None = None,
        task_id: str | None = None,
        performed_by: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Force the deep pipeline for every interactive query.

        The Celery cron path does NOT come through here — it calls
        `run_detector_cycle(workspace_id)` directly.
        """
        ctx = dict(context or {})
        ctx.setdefault("mode", "deep")

        if self._maybe_handle_meta_query(query) is not None:
            return super().execute(
                query,
                execution=execution,
                execution_id=execution_id,
                task_id=task_id,
                performed_by=performed_by,
                context=ctx,
            )

        from components.agents.infrastructure.services.agents_service import (
            get_agent_service,
        )

        service = get_agent_service()
        return service.execute_agent(
            self.agent_id,
            query,
            performed_by=performed_by,
            context=ctx,
        )
