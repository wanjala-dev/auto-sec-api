from __future__ import annotations

from typing import Any, Protocol


class TeamPlanWebhookPort(Protocol):
    def handle_verified_webhook(
        self,
        *,
        event: dict[str, Any],
        workspace: Any | None,
        method: Any | None,
        payment_event: Any | None,
        api_key: str | None,
    ) -> None: ...
