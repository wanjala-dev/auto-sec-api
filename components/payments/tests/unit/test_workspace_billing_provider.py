from __future__ import annotations

from components.payments.application.providers.workspace_billing_provider import (
    WorkspaceBillingProvider,
)
from components.payments.application.service import (
    WorkspaceBillingService,
)


def test_workspace_billing_provider_builds_service():
    service = WorkspaceBillingProvider().build_service()

    assert isinstance(service, WorkspaceBillingService)
    assert service.billing_store.__class__.__name__ == "StripeWorkspaceBillingRepository"
