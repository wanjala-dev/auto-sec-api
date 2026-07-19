from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from components.payments.application.use_cases.complete_payment_method_onboarding_use_case import (
    CompletePaymentMethodOnboardingUseCase,
)
from components.payments.application.use_cases.start_payment_method_onboarding_use_case import (
    StartPaymentMethodOnboardingUseCase,
)
from components.payments.domain.entities.workspace_payment_method_entity import (
    WorkspacePaymentMethodEntity,
)
from components.payments.domain.value_objects import (
    ConnectedPaymentAccount,
    PaymentOnboardingLink,
)


class FakePaymentMethodRepository:
    def __init__(self, method: WorkspacePaymentMethodEntity | None):
        self.method = method
        self.saved_method: WorkspacePaymentMethodEntity | None = None
        self.updated_by_id = None

    def get_method(self, *, method_id):
        if self.method and self.method.id == method_id:
            return replace(self.method)
        return None

    def save_method(self, *, method, updated_by_id=None):
        self.saved_method = replace(method)
        self.updated_by_id = updated_by_id

    def set_primary_method(self, *, method_id, updated_by_id=None):
        raise NotImplementedError


class FakeOnboardingGateway:
    def __init__(
        self,
        *,
        start_result: PaymentOnboardingLink | None = None,
        account_result: ConnectedPaymentAccount | None = None,
    ):
        self.start_result = start_result
        self.account_result = account_result
        self.start_kwargs = None
        self.account_id = None

    def start_workspace_onboarding(self, **kwargs):
        self.start_kwargs = kwargs
        return self.start_result

    def fetch_connected_account(self, *, account_id: str):
        self.account_id = account_id
        return self.account_result


class FakePlanSync:
    def __init__(self):
        self.method_id = None

    def sync_method_plans(self, *, method_id):
        self.method_id = method_id


def build_method(*, provider_slug: str = "stripe") -> WorkspacePaymentMethodEntity:
    return WorkspacePaymentMethodEntity(
        id=uuid4(),
        workspace_id=uuid4(),
        provider_slug=provider_slug,
        status="draft",
        is_primary=False,
        metadata={
            "post_onboard_redirect": "https://frontend.example/success",
            "post_onboard_refresh": "https://frontend.example/refresh",
        },
        credentials={},
        owner_email="owner@example.com",
    )


def test_start_payment_method_onboarding_use_case_persists_state_and_provider_redirect():
    method = build_method()
    repository = FakePaymentMethodRepository(method)
    gateway = FakeOnboardingGateway(
        start_result=PaymentOnboardingLink(
            account_id="acct_123",
            redirect_url="https://connect.stripe.test/link",
            expires_at=1234,
            created_account=True,
        )
    )
    use_case = StartPaymentMethodOnboardingUseCase(repository, gateway)

    result = use_case.execute(
        method_id=method.id,
        state="state_123",
        post_onboard_redirect="https://frontend.example/success",
        post_onboard_refresh="https://frontend.example/refresh",
        callback_success_url="https://api.example/callback?result=success",
        callback_refresh_url="https://api.example/callback?result=refresh",
        updated_by_id=uuid4(),
    )

    assert result.redirect_url == "https://connect.stripe.test/link"
    assert result.state == "state_123"
    assert gateway.start_kwargs["owner_email"] == "owner@example.com"
    assert repository.saved_method is not None
    assert repository.saved_method.status == WorkspacePaymentMethodEntity.STATUS_PENDING
    assert repository.saved_method.provider_account_id == "acct_123"
    assert repository.saved_method.metadata["stripe_connect_state"] == "state_123"
    assert repository.saved_method.credentials["account_id"] == "acct_123"


def test_complete_payment_method_onboarding_use_case_marks_method_active_and_syncs_plans():
    method = build_method()
    method.metadata["stripe_connect_state"] = "state_123"
    method.metadata["stripe_account_id"] = "acct_123"
    repository = FakePaymentMethodRepository(method)
    gateway = FakeOnboardingGateway(
        account_result=ConnectedPaymentAccount(
            account_id="acct_123",
            details_submitted=True,
            charges_enabled=True,
            payouts_enabled=True,
            capabilities={"transfers": "active"},
            requirements={},
        )
    )
    plan_sync = FakePlanSync()
    use_case = CompletePaymentMethodOnboardingUseCase(repository, gateway, plan_sync)

    result = use_case.execute(
        method_id=method.id,
        state="state_123",
        result="success",
        error_code=None,
        error_description=None,
        account_hint=None,
    )

    assert result.status_code == "success"
    assert result.redirect_target == "https://frontend.example/success"
    assert gateway.account_id == "acct_123"
    assert repository.saved_method is not None
    assert repository.saved_method.status == WorkspacePaymentMethodEntity.STATUS_ACTIVE
    assert repository.saved_method.metadata["stripe_charges_enabled"] is True
    assert "stripe_connect_state" not in repository.saved_method.metadata
    assert plan_sync.method_id == method.id


def test_complete_payment_method_onboarding_use_case_rejects_state_mismatch():
    method = build_method()
    method.metadata["stripe_connect_state"] = "expected"
    repository = FakePaymentMethodRepository(method)
    gateway = FakeOnboardingGateway()
    plan_sync = FakePlanSync()
    use_case = CompletePaymentMethodOnboardingUseCase(repository, gateway, plan_sync)

    result = use_case.execute(
        method_id=method.id,
        state="wrong",
        result="success",
        error_code=None,
        error_description=None,
        account_hint=None,
    )

    assert result.status_code == "state_mismatch"
    assert repository.saved_method is not None
    assert repository.saved_method.status == WorkspacePaymentMethodEntity.STATUS_REQUIRES_ACTION
    assert repository.saved_method.last_error == "Stripe onboarding state mismatch."
    assert gateway.account_id is None
