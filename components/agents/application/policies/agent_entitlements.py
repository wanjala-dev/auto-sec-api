"""Re-export shim — actual implementation lives in infrastructure.

All ORM-dependent entitlement logic has been moved to
``components.agents.infrastructure.services.agent_entitlements``
so that the application layer remains free of persistence imports.
Existing call-sites can keep importing from this module.
"""
from components.agents.infrastructure.services.agent_entitlements import (  # noqa: F401
    ensure_workspace_agent_type,
    get_workspace_entitlement_map,
    is_agent_enabled_for_workspace,
    resolve_agent_entitlement,
    resolve_agent_type,
    workspace_ai_enabled,
    workspace_ai_paused,
)
