"""Provider for the workspace settlement-currency reader adapter.

Cross-context callers (sponsorship controllers, mappers) consume this
provider instead of importing the money infrastructure adapter directly.
"""

from __future__ import annotations

from typing import Any


class WorkspaceSettlementCurrencyReaderProvider:
    def adapter(self) -> Any:
        from components.money.infrastructure.adapters.django_workspace_settlement_currency_reader_adapter import (
            DjangoWorkspaceSettlementCurrencyReaderAdapter,
        )

        return DjangoWorkspaceSettlementCurrencyReaderAdapter()


_default = WorkspaceSettlementCurrencyReaderProvider()


def get_workspace_settlement_currency_reader_provider() -> (
    WorkspaceSettlementCurrencyReaderProvider
):
    return _default
