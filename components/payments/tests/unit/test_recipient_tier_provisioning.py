"""Unit tests for finalizing a per-recipient sponsorship tier after save.

``_finalize_recipient_sponsorship_tier`` makes a freshly-saved recipient tier
safe to charge:

1. Its currency is forced to the connected account's settlement currency (never
   the client's input) — a CAD account must charge CAD or the form checkout
   400s on a mismatch.
2. A recurring, fixed-amount tier is provisioned a Stripe price so the form
   recurring checkout can ride its ``price_id``. One-time / custom-amount tiers
   are skipped; provisioning failure is best-effort (never propagates).

It applies ONLY to ``recipient_sponsorship`` plans scoped to a recipient.
"""

from __future__ import annotations

from types import SimpleNamespace

import components.payments.api.controller as ctrl


class _FakeGateway:
    def __init__(self, raises: bool = False):
        self.calls: list = []
        self._raises = raises

    def ensure_plan_resources(self, method, plan):
        self.calls.append((method, plan))
        if self._raises:
            raise RuntimeError("stripe boom")


def _patch_gateway(monkeypatch, gateway):
    class _Prov:
        def get_gateway_for_provider(self, slug):
            return gateway

    monkeypatch.setattr(
        "components.payments.application.providers.make_payment_gateway_provider",
        lambda: _Prov(),
    )


def _method(settlement="cad", provider_slug="stripe"):
    return SimpleNamespace(
        settlement_currency=settlement,
        provider=SimpleNamespace(slug=provider_slug) if provider_slug else None,
    )


class _FakePlan:
    def __init__(self, **kw):
        defaults = dict(
            id="p1",
            context="recipient_sponsorship",
            is_recurring=True,
            custom_amount=False,
            recipient_id="r1",
            currency="cad",
        )
        defaults.update(kw)
        self.__dict__.update(defaults)
        self.saved_fields: list = []

    def save(self, update_fields=None):
        self.saved_fields.append(tuple(update_fields or ()))


class TestFinalizeRecipientSponsorshipTier:
    def test_provisions_a_recurring_fixed_tier(self, monkeypatch):
        gw = _FakeGateway()
        _patch_gateway(monkeypatch, gw)
        ctrl._finalize_recipient_sponsorship_tier(_method(), _FakePlan())
        assert len(gw.calls) == 1

    def test_forces_settlement_currency(self, monkeypatch):
        gw = _FakeGateway()
        _patch_gateway(monkeypatch, gw)
        plan = _FakePlan(currency="usd")  # wrong currency from the client
        ctrl._finalize_recipient_sponsorship_tier(_method(settlement="cad"), plan)
        assert plan.currency == "cad"
        assert any("currency" in fields for fields in plan.saved_fields)

    def test_leaves_matching_currency_untouched(self, monkeypatch):
        gw = _FakeGateway()
        _patch_gateway(monkeypatch, gw)
        plan = _FakePlan(currency="cad")
        ctrl._finalize_recipient_sponsorship_tier(_method(settlement="cad"), plan)
        # No currency re-save (only provisioning may have touched it elsewhere).
        assert all("currency" not in fields for fields in plan.saved_fields)

    def test_skips_one_time_tier_provision(self, monkeypatch):
        gw = _FakeGateway()
        _patch_gateway(monkeypatch, gw)
        ctrl._finalize_recipient_sponsorship_tier(
            _method(), _FakePlan(is_recurring=False)
        )
        assert gw.calls == []

    def test_skips_custom_amount_tier_provision(self, monkeypatch):
        gw = _FakeGateway()
        _patch_gateway(monkeypatch, gw)
        ctrl._finalize_recipient_sponsorship_tier(
            _method(), _FakePlan(custom_amount=True)
        )
        assert gw.calls == []

    def test_ignores_non_recipient_context(self, monkeypatch):
        gw = _FakeGateway()
        _patch_gateway(monkeypatch, gw)
        plan = _FakePlan(context="donation_form", currency="usd")
        ctrl._finalize_recipient_sponsorship_tier(_method(settlement="cad"), plan)
        # Not a recipient tier — neither currency nor provisioning is touched.
        assert plan.currency == "usd"
        assert gw.calls == []

    def test_ignores_workspace_level_plan_without_recipient(self, monkeypatch):
        gw = _FakeGateway()
        _patch_gateway(monkeypatch, gw)
        plan = _FakePlan(recipient_id=None, currency="usd")
        ctrl._finalize_recipient_sponsorship_tier(_method(settlement="cad"), plan)
        assert plan.currency == "usd"
        assert gw.calls == []

    def test_provisioning_failure_never_propagates(self, monkeypatch):
        gw = _FakeGateway(raises=True)
        _patch_gateway(monkeypatch, gw)
        ctrl._finalize_recipient_sponsorship_tier(_method(), _FakePlan())
        assert len(gw.calls) == 1

    def test_skips_provision_when_method_has_no_provider(self, monkeypatch):
        gw = _FakeGateway()
        _patch_gateway(monkeypatch, gw)
        # currency still normalized, but no provider → no provisioning
        plan = _FakePlan(currency="usd")
        ctrl._finalize_recipient_sponsorship_tier(
            _method(settlement="cad", provider_slug=None), plan
        )
        assert plan.currency == "cad"
        assert gw.calls == []
