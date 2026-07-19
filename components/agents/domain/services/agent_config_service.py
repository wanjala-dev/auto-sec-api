"""Domain service for agent configuration logic.

Pure business rules — no ORM, no framework imports.  Used by
infrastructure services and use cases to merge configs, extract
profile details, and validate agent type structures.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Value objects ────────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentTypeConfig:
    """Snapshot of an agent-type definition — framework-free."""

    slug: str
    name: str
    description: str = ""
    default_config: Dict[str, Any] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    required_actions: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    department_tags: List[str] = field(default_factory=list)
    default_run_config: Dict[str, Any] = field(default_factory=dict)
    class_path: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class ProfileDetails:
    """Extracted profile information for an agent type."""

    summary: str
    capabilities: List[str]
    examples: List[str]


# ── Service ──────────────────────────────────────────────────────────

class AgentConfigService:
    """Pure domain logic for agent configuration."""

    @staticmethod
    def merge_config(
        agent_type: AgentTypeConfig,
        override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Merge *agent_type* defaults with caller-supplied *override*.

        Returns a new dict — never mutates the inputs.
        """
        base = deepcopy(agent_type.default_config)
        if agent_type.allowed_tools and "allowed_tools" not in base:
            base["allowed_tools"] = list(agent_type.allowed_tools)
        if agent_type.required_actions and "required_actions" not in base:
            base["required_actions"] = list(agent_type.required_actions)
        if override:
            base.update(override)
        return base

    @staticmethod
    def extract_profile_details(agent_type: AgentTypeConfig) -> ProfileDetails:
        """Pull profile summary, capabilities, and example prompts
        from the agent-type's default config dict.
        """
        config = agent_type.default_config or {}
        profile = config.get("profile") or {} if isinstance(config, dict) else {}

        summary = ""
        capabilities: List[str] = []
        examples: List[str] = []

        if isinstance(profile, dict):
            summary = profile.get("summary") or ""
            capabilities = profile.get("capabilities") or []
            examples = (
                profile.get("sample_prompts")
                or profile.get("examples")
                or []
            )

        if not summary:
            summary = (
                agent_type.description
                or f"Agent focused on {agent_type.name} tasks."
            )
        if not examples:
            examples = [
                f"What can the {agent_type.name} help with?",
                f"Show recent activity handled by the {agent_type.name}.",
                f"Help me with a {agent_type.name} task.",
            ]

        capabilities = [str(c) for c in capabilities if c]
        examples = [str(e) for e in examples if e]
        return ProfileDetails(
            summary=summary,
            capabilities=capabilities,
            examples=examples,
        )

    @staticmethod
    def resolve_alias(
        slug: str,
        alias_map: Dict[str, str],
    ) -> str:
        """Return the canonical slug for *slug*, using *alias_map*."""
        return alias_map.get(slug, slug)

    @staticmethod
    def build_default_display_name(
        agent_type_name: str,
        workspace_id: str,
    ) -> str:
        """Construct the default display name for a new agent profile."""
        return f"{agent_type_name} for workspace {workspace_id}"
