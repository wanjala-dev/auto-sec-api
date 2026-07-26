"""Published seam for the shared DB-router selector.

``set_db_for_router`` pins the active database for the tenant router. The payments
webhook path needs it when handling events outside a normal request; it reaches it
through this application-layer re-export instead of importing ``shared_platform
.infrastructure.middleware.tenant_middlewares`` directly (ADR 0004 infra-boundary series).
"""

from __future__ import annotations

from components.shared_platform.infrastructure.middleware.tenant_middlewares import (
    set_db_for_router,
)

__all__ = ["set_db_for_router"]
