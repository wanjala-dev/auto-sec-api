from __future__ import annotations

from typing import Protocol, Sequence


class ModelNotificationDispatchPort(Protocol):
    def dispatch(
        self,
        *,
        actor,
        workspace,
        verb: str,
        notification_type: str,
        recipients: Sequence,
        metadata: dict | None = None,
        target=None,
    ) -> None:
        ...
