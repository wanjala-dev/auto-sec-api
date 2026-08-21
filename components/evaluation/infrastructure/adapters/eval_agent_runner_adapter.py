"""Run one case against the real agent, in evaluation mode (ADR 0033 D5).

The evaluation mode is applied by ``agents``' own application-layer provider,
``AgentRegistryProvider.run_in_evaluation_mode``, which this adapter calls.
Reaching `AgentRegistry` directly from here would be a cross-context
infrastructure import, which `test_cross_context_infrastructure_boundary`
refuses — correctly. The provider is the composition root and the only legal
door, so the evaluation-mode kwarg is set there, at construction.
"""

from __future__ import annotations

import logging
import uuid

from components.evaluation.application.ports.eval_ports import (
    AgentOutcome,
    AgentRunnerPort,
    EvalCaseInput,
)

logger = logging.getLogger(__name__)


def _query_for(case: EvalCaseInput) -> str:
    """Render a case into the prompt the agent under test receives."""
    lines = [f"Evaluation case: {case.scenario or case.case_id}", ""]
    for key, value in (case.prompt_inputs or {}).items():
        lines.append(f"{key}: {value}")
    if case.solution_criteria:
        lines.append("")
        lines.append("Handle this as you normally would.")
    return "\n".join(lines)


class EvalAgentRunnerAdapter(AgentRunnerPort):
    """Executes the agent under test with every write refused."""

    def __init__(self, *, user_id=None) -> None:
        self._user_id = user_id

    def run_case(
        self, *, agent_type: str, workspace_id: str, case: EvalCaseInput, model_slug: str
    ) -> AgentOutcome:
        from components.agents.application.providers.agent_registry_provider import (
            get_agent_registry_provider,
        )

        try:
            result = get_agent_registry_provider().run_in_evaluation_mode(
                agent_type=agent_type,
                agent_id=f"eval-{uuid.uuid4()}",
                user_id=self._user_id,
                workspace_id=workspace_id,
                model_slug=model_slug,
                query=_query_for(case),
            )
        except Exception as exc:
            logger.exception("eval_agent_run_failed type=%s case=%s", agent_type, case.case_id)
            return AgentOutcome(output="", error=str(exc))

        # `success: False` is a real outcome for a case, not an exception. It is
        # carried through as an error string so the result row says WHY rather
        # than showing an empty output with no explanation.
        error = "" if result.get("success", True) else str(result.get("error") or "agent reported failure")
        output = result.get("response") or result.get("result") or result.get("output") or ""

        return AgentOutcome(
            output=str(output),
            deep_run_id=str(result["deep_run_id"]) if result.get("deep_run_id") else None,
            cost_usd=float(result.get("cost_usd") or 0.0),
            error=error,
        )


__all__ = ["EvalAgentRunnerAdapter"]
