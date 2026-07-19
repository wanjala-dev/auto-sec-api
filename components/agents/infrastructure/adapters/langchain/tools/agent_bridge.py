"""LangChain tool helpers for delegating work to other domain agents."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Tuple

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


def get_agent_service():
    """Deferred import helper so tests can patch at module scope."""
    from components.agents.infrastructure.services.agents_service import get_agent_service as _get_agent_service

    return _get_agent_service()


class AgentCallInput(BaseModel):
    query: str = Field(..., description="Natural language instruction for the target agent.")
    context: Dict[str, Any] = Field(default_factory=dict, description="Structured context payload.")


def create_agent_tool(teammate_agent, agent_type: str, description: str) -> Tuple[StructuredTool, Callable[[str, Dict[str, Any]], Dict[str, Any]]]:
    """Return a StructuredTool that dispatches to the given agent type plus the raw invoker."""

    workspace_id = teammate_agent.workspace_id

    def _invoke(query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        from components.agents.application.policies.agent_entitlements import resolve_agent_entitlement

        agent_service = get_agent_service()
        workspace = teammate_agent._get_workspace()  # pragma: no cover - convenience reuse
        if not workspace:
            raise ValueError("Workspace context unavailable for agent invocation")

        teammate_profile = teammate_agent.action_service.ensure_teammate(workspace)

        allowed, reason, canonical_slug = resolve_agent_entitlement(str(workspace.id), agent_type)
        if not allowed:
            return {
                "success": False,
                "code": "agent_not_entitled",
                "reason": reason,
                "agent_type": canonical_slug or agent_type,
            }

        run_context = context.get("run_context") if isinstance(context, dict) else None
        department_id = (
            context.get("department_id")
            if isinstance(context, dict)
            else None
        ) or (run_context.get("department_id") if isinstance(run_context, dict) else None)
        try:
            agent_info = agent_service.get_or_create_agent(
                agent_type=agent_type,
                user_id=str(teammate_profile.user_id),
                workspace_id=str(workspace.id),
                department_id=department_id,
            )
            return agent_service.execute_agent(
                agent_info['agent_id'],
                query,
                performed_by=str(teammate_profile.user_id),
                context=context,
            ) or {}
        except PermissionError as exc:
            return {"success": False, "error": str(exc), "agent_type": agent_type}

    def _tool_fn(inputs: AgentCallInput | str | Dict[str, Any]) -> str:
        if isinstance(inputs, AgentCallInput):
            query = inputs.query
            context = inputs.context
        elif isinstance(inputs, str):
            query = inputs
            context = {}
        elif isinstance(inputs, dict):
            query = inputs.get("query", "")
            context = inputs.get("context") or {}
        else:  # pragma: no cover - defensive guard
            raise TypeError(f"Unsupported tool input: {type(inputs)!r}")

        if not isinstance(context, dict):  # pragma: no cover - malformed payload
            raise TypeError("Tool context must be a mapping")

        result = _invoke(query, context)
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            return json.dumps({'result': result.get('result'), 'state': result.get('state')}, ensure_ascii=False)

    tool = StructuredTool.from_function(
        func=_tool_fn,
        name=f"call_{agent_type}",
        description=description,
        args_schema=AgentCallInput,
    )
    return tool, _invoke


__all__ = [
    "create_agent_tool",
    "get_agent_service",
]
