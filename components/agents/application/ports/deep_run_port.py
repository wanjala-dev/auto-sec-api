"""Port for deep-run orchestration — plan execution and LLM-driven planning.

Adapters wrap the concrete ``run_plan_with_agent`` / ``plan_and_run_with_llm``
service functions so the application layer stays framework-free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DeepRunPort(ABC):
    """Abstract contract for deep-run orchestration backends."""

    @abstractmethod
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
        """Execute a pre-built plan with the specified agent type."""
        ...

    @abstractmethod
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
        """Generate a plan from *goal* via LLM, then execute it."""
        ...
