"""Use cases: deep-run plan execution and LLM-driven plan-and-run.

Extracts the orchestration logic from ``agents_controller.deep_run_plan`` and
``agents_controller.deep_plan_and_run``:

    1. Attach workspace/team defaults to plan tasks (pure domain logic)
    2. Delegate execution via DeepRunPort

PlanSpec validation stays at the controller boundary (presentation concern).
The use case receives a validated plan object (opaque ``Any``).

Framework-free — no Django, DRF, or apps.* imports.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from components.agents.application.commands.deep_run_command import (
    DeepPlanAndRunCommand,
    DeepRunFailure,
    DeepRunPlanCommand,
    DeepRunSuccess,
)
from components.agents.application.ports.deep_run_port import DeepRunPort
from components.shared_kernel.application.handlers import CommandHandler


DeepRunPlanResult = DeepRunSuccess | DeepRunFailure
DeepPlanAndRunResult = DeepRunSuccess | DeepRunFailure


def default_plan_payload(
    plan_data: dict, workspace_id: str, team_id: str | None
) -> dict:
    """Attach workspace/team defaults to tasks when missing (pure function).

    Exposed for use by both the use case and the controller.
    """
    tasks = plan_data.get("tasks") or []
    for task in tasks:
        task.setdefault("workspace_id", workspace_id)
        if team_id:
            task.setdefault("team_id", team_id)
    return plan_data


class DeepRunPlanUseCase(CommandHandler[DeepRunPlanCommand]):
    """Execute a pre-built, validated plan with an agent.

    The controller is responsible for PlanSpec validation and passes
    the validated plan object through.
    """

    def __init__(self, *, deep_run: DeepRunPort) -> None:
        self._deep_run = deep_run

    def handle(self, command: DeepRunPlanCommand) -> Any:
        """CommandHandler implementation."""
        # Note: validated_plan must be passed separately via execute()
        # This is a limitation due to the additional parameter requirement
        return self.execute(command, validated_plan=None)

    def execute(
        self, command: DeepRunPlanCommand, *, validated_plan: Any
    ) -> DeepRunPlanResult:
        plan_id = getattr(validated_plan, "plan_id", "") or str(_uuid.uuid4())
        thread_id = command.thread_id or plan_id

        try:
            state = self._deep_run.run_plan(
                plan=validated_plan,
                agent_type=command.agent_type,
                user_id=command.user_id,
                workspace_id=command.workspace_id,
                agent_config=command.agent_config,
                thread_id=thread_id,
                sync_to_kanban=command.sync_to_kanban,
            )
        except Exception as exc:
            return DeepRunFailure(error=str(exc), status_code=500)

        return DeepRunSuccess(plan_id=plan_id, state=state)


class DeepPlanAndRunUseCase(CommandHandler[DeepPlanAndRunCommand]):
    """One-shot: LLM generates a plan from *goal*, then executes it."""

    def __init__(self, *, deep_run: DeepRunPort) -> None:
        self._deep_run = deep_run

    def handle(self, command: DeepPlanAndRunCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command)

    def execute(self, command: DeepPlanAndRunCommand) -> DeepPlanAndRunResult:
        plan_id = command.plan_id or str(_uuid.uuid4())

        try:
            state = self._deep_run.plan_and_run(
                goal=command.goal,
                plan_id=plan_id,
                agent_type=command.agent_type,
                user_id=command.user_id,
                workspace_id=command.workspace_id,
                team_id=command.team_id,
                agent_config=command.agent_config,
                model_name=command.model_name,
                sync_to_kanban=command.sync_to_kanban,
                extra_context=command.extra_context,
                deep_pack=command.deep_pack,
            )
        except Exception as exc:
            return DeepRunFailure(error=str(exc), status_code=500)

        return DeepRunSuccess(plan_id=plan_id, state=state)
