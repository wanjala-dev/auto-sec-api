"""Tests that settlement_currency gets populated at Stripe connect time.

Covers the three layers the connect flow touches:

- ConnectedPaymentAccount (value object): carries default_currency.
- complete_stripe_onboarding (entity method): writes
  settlement_currency from the account.
- PaymentMethodManagementRepository.save_method: persists the field.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.payments.domain.entities.workspace_payment_method_entity import (
    WorkspacePaymentMethodEntity,
)
from components.payments.domain.value_objects import ConnectedPaymentAccount


def _make_entity() -> WorkspacePaymentMethodEntity:
    return WorkspacePaymentMethodEntity(
        id=uuid4(),
        workspace_id=uuid4(),
        provider_slug="stripe",
        status="pending",
        is_primary=False,
    )


class TestConnectedPaymentAccount:
    def test_default_currency_defaults_to_none(self):
        account = ConnectedPaymentAccount(
            account_id="acct_test",
            details_submitted=True,
            charges_enabled=True,
            payouts_enabled=True,
            capabilities={},
            requirements={},
        )
        assert account.default_currency is None

    def test_default_currency_can_be_set(self):
        account = ConnectedPaymentAccount(
            account_id="acct_test",
            details_submitted=True,
            charges_enabled=True,
            payouts_enabled=True,
            capabilities={},
            requirements={},
            default_currency="CAD",
        )
        assert account.default_currency == "CAD"


class TestCompleteStripeOnboarding:
    def test_sets_settlement_currency_from_account(self):
        entity = _make_entity()
        account = ConnectedPaymentAccount(
            account_id="acct_test",
            details_submitted=True,
            charges_enabled=True,
            payouts_enabled=True,
            capabilities={},
            requirements={},
            default_currency="EUR",
        )
        entity.complete_stripe_onboarding(account)
        assert entity.settlement_currency == "EUR"
        assert entity.provider_account_id == "acct_test"
        assert entity.status == entity.STATUS_ACTIVE

    def test_uppercases_lowercase_stripe_currency(self):
        """Stripe returns default_currency lowercase. The entity must
        normalize so downstream queries/validators can compare without
        casing rules."""
        entity = _make_entity()
        account = ConnectedPaymentAccount(
            account_id="acct_test",
            details_submitted=True,
            charges_enabled=True,
            payouts_enabled=True,
            capabilities={},
            requirements={},
            default_currency="cad",
        )
        entity.complete_stripe_onboarding(account)
        assert entity.settlement_currency == "CAD"

    def test_leaves_existing_currency_when_account_missing_default(self):
        entity = _make_entity()
        entity.settlement_currency = "USD"
        account = ConnectedPaymentAccount(
            account_id="acct_test",
            details_submitted=True,
            charges_enabled=True,
            payouts_enabled=True,
            capabilities={},
            requirements={},
            default_currency=None,
        )
        entity.complete_stripe_onboarding(account)
        assert entity.settlement_currency == "USD"

    def test_status_degrades_when_charges_disabled(self):
        entity = _make_entity()
        account = ConnectedPaymentAccount(
            account_id="acct_test",
            details_submitted=False,
            charges_enabled=False,
            payouts_enabled=False,
            capabilities={},
            requirements={},
            default_currency="GBP",
        )
        entity.complete_stripe_onboarding(account)
        # Currency still lands even though the rest of onboarding is
        # incomplete — next admin hit of the account link just
        # refreshes capabilities, not the currency.
        assert entity.settlement_currency == "GBP"
        assert entity.status == entity.STATUS_REQUIRES_ACTION


@pytest.mark.django_db
class TestSaveMethodPersistsSettlementCurrency:
    def test_save_method_writes_settlement_currency(self, django_db_setup):
        from uuid import uuid4

        from components.payments.infrastructure.repositories.payment_method_management_repository import (
            PaymentMethodManagementRepository,
        )
        from infrastructure.persistence.users.models import CustomUser
        from infrastructure.persistence.workspaces.models import Workspace
        from infrastructure.persistence.workspaces.payments.models import (
            PaymentProvider,
            WorkspacePaymentMethod,
        )

        user = CustomUser.objects.create_user(
            username=f"connect-{uuid4()}",
            email=f"{uuid4()}@example.com",
            password="x",
        )
        workspace = Workspace.objects.create(
            workspace_name="Test WS",
            workspace_owner=user,
            default_currency="USD",
        )
        provider, _ = PaymentProvider.objects.get_or_create(
            slug="stripe", defaults={"display_name": "Stripe"}
        )
        orm = WorkspacePaymentMethod.objects.create(
            workspace=workspace,
            provider=provider,
            display_name="Stripe",
            status=WorkspacePaymentMethod.STATUS_DRAFT,
            provider_account_id="",
        )

        entity = WorkspacePaymentMethodEntity(
            id=orm.id,
            workspace_id=workspace.id,
            provider_slug="stripe",
            status="active",
            is_primary=False,
            provider_account_id="acct_persist_test",
            settlement_currency="NZD",
        )

        PaymentMethodManagementRepository().save_method(method=entity)

        orm.refresh_from_db()
        assert orm.settlement_currency == "NZD"
        assert orm.provider_account_id == "acct_persist_test"
