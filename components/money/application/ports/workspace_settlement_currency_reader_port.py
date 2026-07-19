"""Port for reading a workspace's settlement currency from its payment rail.

The settlement currency is a property of the payment provider account
(Stripe Connect ``Account.default_currency``, persisted onto
``WorkspacePaymentMethod.settlement_currency`` at connect time) — never a
hardcoded value. Read-path callers (e.g. the public recipient grid) use
this to display amounts in the currency the workspace actually settles in.

This is a CHEAP, read-only lookup of the persisted column — it never makes
a live Stripe call, so it is safe to use on a request thread.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class WorkspaceSettlementCurrencyReaderPort(ABC):
    @abstractmethod
    def resolve(self, *, workspace_id: str) -> str | None:
        """Return the workspace's settlement currency (uppercase ISO-4217).

        Resolution: the primary active payment method's persisted
        ``settlement_currency``, else the first method by sort order.
        Returns ``None`` when the workspace has no payment method with a
        persisted settlement currency yet — the caller decides the
        fallback (typically the workspace default currency).
        """
