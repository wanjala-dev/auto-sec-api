"""Port for writing a workspace's display/operating currency.

``Workspace.default_currency`` is a CACHE of the connected account's
settlement currency, NOT a second source of truth. The single authority is
``WorkspacePaymentMethod.settlement_currency`` (sourced from the Stripe
Connect ``Account.default_currency``), read via
``WorkspaceSettlementCurrencyReaderPort``. This writer keeps the cache in
sync — see ``docs/plans/CURRENCY_SINGLE_SOURCE_OF_TRUTH.md`` (P0c).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class WorkspaceCurrencyWriterPort(ABC):
    @abstractmethod
    def write(self, *, workspace_id: str, currency: str) -> bool:
        """Set ``Workspace.default_currency`` to ``currency`` if different.

        Returns ``True`` when the stored value actually changed, ``False``
        when it was already in sync (or the inputs were empty). Never raises
        on a no-op.
        """
