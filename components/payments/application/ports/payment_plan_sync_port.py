from __future__ import annotations

from typing import Protocol
from uuid import UUID


class PaymentPlanSyncPort(Protocol):
    def sync_method_plans(self, *, method_id: UUID) -> None: ...
