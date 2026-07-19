"""Infrastructure adapter wrapping the deep-run service functions behind DeepRunPort."""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.deep_run_port import DeepRunPort


class DeepRunAdapter(DeepRunPort):
    """Delegates to ``apps.ai.agents.deep`` orchestration functions."""

    def run_plan(
        self,
        *,
        plan: Any,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        agent_config: dict,
        thread_id: str,
        sync_to_kanban: bool = True,
    ) -> dict:
        from components.agents.infrastructure.services.deep_service import run_plan_with_agent

        return run_plan_with_agent(
            plan=plan,
            agent_type=agent_type,
            user_id=user_id,
            workspace_id=workspace_id,
            agent_config=agent_config,
            thread_id=thread_id,
            sync_to_kanban=sync_to_kanban,
        )

    def plan_and_run(
        self,
        *,
        goal: str,
        plan_id: str,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        team_id: str | None = None,
        agent_config: dict,
        model_name: str | None = None,
        sync_to_kanban: bool = True,
        extra_context: dict | None = None,
        deep_pack: str | None = None,
    ) -> dict:
        from components.agents.infrastructure.services.deep_service import plan_and_run_with_llm

        return plan_and_run_with_llm(
            goal=goal,
            plan_id=plan_id,
            agent_type=agent_type,
            user_id=user_id,
            workspace_id=workspace_id,
            team_id=team_id,
            agent_config=agent_config,
            model_name=model_name,
            sync_to_kanban=sync_to_kanban,
            extra_context=extra_context,
            deep_pack=deep_pack,
        )
