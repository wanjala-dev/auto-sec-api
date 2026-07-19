"""Django adapter for WorkspaceSettlementCurrencyReaderPort.

Reads the persisted ``settlement_currency`` column off the workspace's
payment method(s). No live Stripe call — this is a single indexed read,
safe on the request thread. Mirrors the write-side adapter's direct,
single-column access to ``WorkspacePaymentMethod``.
"""

from __future__ import annotations

from ...application.ports.workspace_settlement_currency_reader_port import (
    WorkspaceSettlementCurrencyReaderPort,
)


class DjangoWorkspaceSettlementCurrencyReaderAdapter(
    WorkspaceSettlementCurrencyReaderPort
):
    def resolve(self, *, workspace_id: str) -> str | None:
        from infrastructure.persistence.workspaces.payments.models import (
            WorkspacePaymentMethod,
        )

        if not workspace_id:
            return None

        # Primary active method first, then sort_order, then oldest. Pick
        # the first one that actually carries a persisted settlement
        # currency (older accounts may not have been backfilled yet).
        currencies = (
            WorkspacePaymentMethod.objects.filter(
                workspace_id=workspace_id, is_deleted=False
            )
            .order_by("-is_primary", "sort_order", "created_at")
            .values_list("settlement_currency", flat=True)
        )
        for value in currencies:
            normalized = (value or "").strip().upper()
            if normalized:
                return normalized
        return None
