"""Mapping from agent_type to source_domain (bounded context).

Used by emitters that don't supply ``source_domain`` explicitly on the
``AIActionCreated`` event. Keep the keys byte-identical to the
``@register_agent`` decorator names in
``components/agents/infrastructure/adapters/langchain/agents/``.
"""

from __future__ import annotations

_AGENT_TYPE_TO_DOMAIN: dict[str, str] = {
    "project_agent": "project",
    "task_agent": "project",
    "user_agent": "identity",
    "ai_teammate": "general",
}


def resolve_source_domain(agent_type: str) -> str:
    """Return the bounded-context domain for *agent_type*.

    Unknown agent types fall back to "general" so findings never drop on the
    floor when a new specialist is added before the map is updated.
    """
    if not agent_type:
        return "general"
    return _AGENT_TYPE_TO_DOMAIN.get(agent_type.strip().lower(), "general")
