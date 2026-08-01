"""Resource DTO: triage-agent capability state for a workspace.

Serializes ``WorkspaceAgentCapabilityResult`` from the agents context. Carries
ONLY the boolean capability map (no secrets, no agent internals) — the FE reads
``capabilities.open_draft_pr`` to render the toggle.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TriageCapabilityResource:
    workspace_id: str
    agent_type: str
    capabilities: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_result(cls, result) -> TriageCapabilityResource:
        return cls(
            workspace_id=str(result.workspace_id),
            agent_type=result.agent_type,
            capabilities={key: bool(value) for key, value in (result.capabilities or {}).items()},
        )

    def to_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "agent_type": self.agent_type,
            "capabilities": self.capabilities,
        }
