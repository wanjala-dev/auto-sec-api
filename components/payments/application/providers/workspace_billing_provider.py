from __future__ import annotations

from components.payments.application.service import (
    WorkspaceBillingService,
)
from components.payments.infrastructure.repositories.stripe_workspace_billing_repository import (
    StripeWorkspaceBillingRepository,
)


class WorkspaceBillingProvider:
    """Composition root for workspace billing customer/card management."""

    def build_service(self) -> WorkspaceBillingService:
        return WorkspaceBillingService(
            billing_store=StripeWorkspaceBillingRepository(),
        )
