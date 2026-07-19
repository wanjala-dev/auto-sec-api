from __future__ import annotations

from typing import Any, Protocol


class PaymentFlowStatePort(Protocol):
    def mark_succeeded(
        self,
        *,
        order: Any | None,
        attempt: Any | None,
    ) -> None: ...

    def mark_processing(
        self,
        *,
        order: Any | None,
        attempt: Any | None,
        gateway_reference: str,
        gateway_reference_type: str,
    ) -> None: ...

    def mark_failed(
        self,
        *,
        order: Any | None,
        attempt: Any | None,
        message: str,
    ) -> None: ...

    def mark_requires_action(
        self,
        *,
        order: Any | None,
        attempt: Any | None,
        message: str,
    ) -> None: ...

    def mark_canceled(
        self,
        *,
        order: Any | None,
        attempt: Any | None,
        message: str,
    ) -> None: ...
