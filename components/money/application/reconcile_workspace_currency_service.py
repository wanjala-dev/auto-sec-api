"""Reconcile a workspace's display currency to its connected account.

The single source of truth for "what currency does this workspace operate in"
is the connected payment account's settlement currency
(``WorkspacePaymentMethod.settlement_currency``, sourced from Stripe Connect's
``Account.default_currency``). ``Workspace.default_currency`` is a cache of
that value, read by serializers/dashboards. This service keeps the cache in
sync — call it whenever a workspace's connected account (or its settlement
currency) is established or changes, and from the backfill command.

See ``docs/plans/CURRENCY_SINGLE_SOURCE_OF_TRUTH.md`` (P0c).
"""

from __future__ import annotations

from dataclasses import dataclass

from components.money.application.ports.workspace_currency_writer_port import (
    WorkspaceCurrencyWriterPort,
)
from components.money.application.ports.workspace_settlement_currency_reader_port import (
    WorkspaceSettlementCurrencyReaderPort,
)


@dataclass(frozen=True)
class ReconcileWorkspaceCurrencyResult:
    workspace_id: str
    settlement_currency: str | None
    changed: bool


@dataclass
class ReconcileWorkspaceCurrency:
    reader: WorkspaceSettlementCurrencyReaderPort
    writer: WorkspaceCurrencyWriterPort

    def execute(self, *, workspace_id: str) -> ReconcileWorkspaceCurrencyResult:
        currency = self.reader.resolve(workspace_id=workspace_id)
        changed = False
        if currency:
            changed = self.writer.write(workspace_id=workspace_id, currency=currency)
        return ReconcileWorkspaceCurrencyResult(
            workspace_id=str(workspace_id),
            settlement_currency=currency,
            changed=changed,
        )
