"""Infrastructure adapter for agent entitlement checks."""

from __future__ import annotations

from components.agents.application.ports.entitlement_port import EntitlementPort


class EntitlementAdapter(EntitlementPort):

    def is_agent_enabled_for_workspace(self, workspace_id: str, agent_type: str) -> bool:
        from components.agents.application.policies.agent_entitlements import is_agent_enabled_for_workspace
        return is_agent_enabled_for_workspace(workspace_id, agent_type)
