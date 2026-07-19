"""Provider/composition root for the agents permissions service.

Driving adapters (DRF permission classes in ``components/agents/api``)
and other controllers consume :class:`AgentPermissionsProvider` instead
of importing the concrete infrastructure service directly. Keeps the
API layer's import graph free of infrastructure dependencies — the
test ``test_controllers_do_not_import_concrete_adapters`` enforces
this.

The concrete helpers in
``components.agents.infrastructure.services.agent_permissions_service``
are plain module-level functions (not classes), so the provider's
methods lazy-import each helper and delegate to it. Module load stays
cheap; tests can monkeypatch ``provider.ai_can`` /
``provider.ensure_ai_grant`` etc. without dragging in Django at test
discovery time.
"""

from __future__ import annotations

from typing import Any, Optional


class AgentPermissionsProvider:
    """Driving-side façade for the agents permissions service."""

    def ai_can(
        self,
        workspace_id: str,
        principal_id: Optional[str],
        action: str,
        resource: Optional[str] = None,
        *,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> bool:
        from components.agents.infrastructure.services.agent_permissions_service import (
            ai_can as _ai_can,
        )

        return _ai_can(
            workspace_id,
            principal_id,
            action,
            resource,
            scope_type=scope_type,
            scope_id=scope_id,
        )

    def ensure_ai_grant(
        self,
        workspace_id: str,
        principal_id: str,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
        actions: list[str] | None = None,
    ) -> Any:
        from components.agents.infrastructure.services.agent_permissions_service import (
            ensure_ai_grant as _ensure_ai_grant,
        )

        return _ensure_ai_grant(
            workspace_id,
            principal_id,
            scope_type=scope_type,
            scope_id=scope_id,
            actions=actions,
        )

    def ensure_ai_identity(self, workspace: Any) -> tuple:
        from components.agents.infrastructure.services.agent_permissions_service import (
            ensure_ai_identity as _ensure_ai_identity,
        )

        return _ensure_ai_identity(workspace)

    def ensure_agents_team(self, workspace: Any, ai_user: Any) -> Any:
        from components.agents.infrastructure.services.agent_permissions_service import (
            ensure_agents_team as _ensure_agents_team,
        )

        return _ensure_agents_team(workspace, ai_user)


_default = AgentPermissionsProvider()


def get_agent_permissions_provider() -> AgentPermissionsProvider:
    """Return the default provider — composition root for the agents
    permissions service. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
