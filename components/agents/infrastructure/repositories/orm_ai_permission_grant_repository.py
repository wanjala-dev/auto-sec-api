"""ORM adapter implementing :class:`AiPermissionGrantPort`.

Disables a workspace principal's AI permission grants in one ``.update()`` — the
exact write ``ai_teammate_facade.disable_teammate`` did inline, moved behind the
port so the facade no longer imports persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from components.agents.application.ports.ai_permission_grant_port import AiPermissionGrantPort


class OrmAiPermissionGrantRepository(AiPermissionGrantPort):
    def disable_grants_for_principal(self, *, workspace: Any, principal: Any) -> int:
        from infrastructure.persistence.ai.models import AIPermissionGrant

        return AIPermissionGrant.objects.filter(workspace=workspace, principal=principal).update(
            status=AIPermissionGrant.STATUS_DISABLED,
            updated_at=datetime.now(UTC),
        )
