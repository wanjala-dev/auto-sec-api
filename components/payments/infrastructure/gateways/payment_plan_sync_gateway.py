from __future__ import annotations

from uuid import UUID

from components.payments.application.ports.payment_gateway_provider_port import (
    PaymentGatewayProviderPort,
)
from components.payments.application.ports.payment_plan_sync_port import PaymentPlanSyncPort
from infrastructure.persistence.workspaces.payments.models import WorkspacePaymentMethod


class PaymentPlanSyncGateway(PaymentPlanSyncPort):
    """Sync active method plans through the provider chosen at composition time."""

    def __init__(self, gateway_provider: PaymentGatewayProviderPort):
        self.gateway_provider = gateway_provider

    def sync_method_plans(self, *, method_id: UUID) -> None:
        method = WorkspacePaymentMethod.objects.get(id=method_id, is_deleted=False)
        gateway = self.gateway_provider.get_gateway_for_provider(method.provider.slug)
        for plan in method.plans.filter(is_active=True):
            gateway.ensure_plan_resources(method, plan)
