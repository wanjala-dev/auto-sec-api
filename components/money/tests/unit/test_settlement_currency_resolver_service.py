"""Unit tests for SettlementCurrencyResolver.

Covers the four-step precedence chain: preferred → method.settlement_currency
→ live StripeAccountCurrencyPort (+persist) → fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from components.money.application.ports.payment_method_settlement_currency_writer_port import (
    PaymentMethodSettlementCurrencyWriterPort,
)
from components.money.application.ports.stripe_account_currency_port import (
    StripeAccountCurrencyPort,
)
from components.money.application.settlement_currency_resolver_service import (
    SettlementCurrencyResolver,
)


@dataclass
class _StubMethod:
    id: UUID = field(default_factory=uuid4)
    provider_account_id: str = "acct_test"
    settlement_currency: str | None = None


class _StubStripePort(StripeAccountCurrencyPort):
    def __init__(self, currency: str | None):
        self.currency = currency
        self.calls: list[str] = []

    def resolve_default_currency(self, provider_account_id: str) -> str | None:
        self.calls.append(provider_account_id)
        return self.currency


class _StubWriter(PaymentMethodSettlementCurrencyWriterPort):
    def __init__(self):
        self.writes: list[tuple[UUID, str]] = []

    def persist_settlement_currency(
        self, *, method_id: UUID, settlement_currency: str
    ) -> None:
        self.writes.append((method_id, settlement_currency))


class TestSettlementCurrencyResolver:
    def test_preferred_wins_over_settlement_currency(self):
        method = _StubMethod(settlement_currency="CAD")
        resolver = SettlementCurrencyResolver()

        result = resolver.resolve(method=method, preferred="eur")

        assert result == "EUR"

    def test_falls_back_to_method_settlement_currency_when_no_preferred(self):
        method = _StubMethod(settlement_currency="cad")
        resolver = SettlementCurrencyResolver()

        result = resolver.resolve(method=method, preferred=None)

        assert result == "CAD"

    def test_empty_preferred_is_ignored(self):
        method = _StubMethod(settlement_currency="CAD")
        resolver = SettlementCurrencyResolver()

        result = resolver.resolve(method=method, preferred="")

        assert result == "CAD"

    def test_live_resolves_via_stripe_port_when_settlement_currency_missing(self):
        method = _StubMethod(settlement_currency=None)
        stripe = _StubStripePort("CAD")
        writer = _StubWriter()
        resolver = SettlementCurrencyResolver(
            stripe_account_currency_port=stripe,
            settlement_currency_writer=writer,
        )

        result = resolver.resolve(method=method, preferred=None)

        assert result == "CAD"
        assert stripe.calls == ["acct_test"]
        assert writer.writes == [(method.id, "CAD")]

    def test_live_resolution_updates_method_in_memory_for_downstream_validator(self):
        """The validator reads method.settlement_currency on the same
        request — so after a live resolve we must mutate the entity in
        memory, not just persist to the DB.
        """
        method = _StubMethod(settlement_currency=None)
        stripe = _StubStripePort("CAD")
        writer = _StubWriter()
        resolver = SettlementCurrencyResolver(
            stripe_account_currency_port=stripe,
            settlement_currency_writer=writer,
        )

        resolver.resolve(method=method, preferred=None)

        assert method.settlement_currency == "CAD"

    def test_skips_stripe_when_no_provider_account_id(self):
        method = _StubMethod(provider_account_id="", settlement_currency=None)
        stripe = _StubStripePort("CAD")
        resolver = SettlementCurrencyResolver(
            stripe_account_currency_port=stripe,
        )

        result = resolver.resolve(method=method, preferred=None)

        assert result == "USD"
        assert stripe.calls == []

    def test_falls_back_to_default_when_stripe_returns_none(self):
        method = _StubMethod(settlement_currency=None)
        stripe = _StubStripePort(None)
        resolver = SettlementCurrencyResolver(
            stripe_account_currency_port=stripe,
        )

        result = resolver.resolve(method=method, preferred=None, fallback="eur")

        assert result == "EUR"
        assert stripe.calls == ["acct_test"]

    def test_no_stripe_port_configured_skips_live_resolve(self):
        method = _StubMethod(settlement_currency=None)
        resolver = SettlementCurrencyResolver()

        result = resolver.resolve(method=method, preferred=None)

        assert result == "USD"

    def test_writer_failure_does_not_break_resolution(self):
        class _BlowUpWriter(PaymentMethodSettlementCurrencyWriterPort):
            def persist_settlement_currency(
                self, *, method_id: UUID, settlement_currency: str
            ) -> None:
                raise RuntimeError("db down")

        method = _StubMethod(settlement_currency=None)
        stripe = _StubStripePort("CAD")
        resolver = SettlementCurrencyResolver(
            stripe_account_currency_port=stripe,
            settlement_currency_writer=_BlowUpWriter(),
        )

        # Persistence is best-effort — we still return the resolved
        # currency even when the write fails, so the checkout proceeds.
        result = resolver.resolve(method=method, preferred=None)

        assert result == "CAD"
