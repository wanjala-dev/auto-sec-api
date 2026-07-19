"""Provider for the workspace-currency reconciler.

Cross-context callers (the payments onboarding wiring, the backfill command)
consume this provider instead of importing money's infrastructure adapters
directly — keeping the cross-context boundary at the application layer.
"""

from __future__ import annotations

from components.money.application.reconcile_workspace_currency_service import (
    ReconcileWorkspaceCurrency,
)


class ReconcileWorkspaceCurrencyProvider:
    def build(self) -> ReconcileWorkspaceCurrency:
        from components.money.infrastructure.adapters.django_workspace_settlement_currency_reader_adapter import (
            DjangoWorkspaceSettlementCurrencyReaderAdapter,
        )
        from components.money.infrastructure.adapters.django_workspace_currency_writer_adapter import (
            DjangoWorkspaceCurrencyWriterAdapter,
        )

        return ReconcileWorkspaceCurrency(
            reader=DjangoWorkspaceSettlementCurrencyReaderAdapter(),
            writer=DjangoWorkspaceCurrencyWriterAdapter(),
        )


_default = ReconcileWorkspaceCurrencyProvider()


def get_reconcile_workspace_currency_provider() -> ReconcileWorkspaceCurrencyProvider:
    return _default
