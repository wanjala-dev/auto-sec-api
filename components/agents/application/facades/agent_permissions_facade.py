"""Re-export shim — actual implementations live in infrastructure and api layers.

ORM-dependent grant/identity logic has been moved to
``components.agents.infrastructure.services.agent_permissions_service``
so that the application layer remains free of persistence imports.

The DRF permission class ``AgentAIPermission`` has been moved to
``components.agents.api.permissions`` where it belongs as a primary adapter.

Existing call-sites can keep importing from this module.
"""
from components.agents.infrastructure.services.agent_permissions_service import (  # noqa: F401
    ai_can,
    ensure_ai_grant,
    ensure_ai_identity,
    ensure_agents_team,
)

from components.agents.api.permissions import AgentAIPermission  # noqa: F401
