"""Django adapter for PaymentMethodSettlementCurrencyWriterPort.

Writes a single field (`settlement_currency`) on
``WorkspacePaymentMethod``. We avoid going through
``PaymentMethodManagementRepository.save_method`` because that path
overwrites several other fields and re-encrypts credentials — overkill
for backfilling one column.
"""

from __future__ import annotations

import logging
from uuid import UUID

from ...application.ports.payment_method_settlement_currency_writer_port import (
    PaymentMethodSettlementCurrencyWriterPort,
)

logger = logging.getLogger(__name__)


class DjangoPaymentMethodSettlementCurrencyWriterAdapter(
    PaymentMethodSettlementCurrencyWriterPort
):
    def persist_settlement_currency(
        self, *, method_id: UUID, settlement_currency: str
    ) -> None:
        from infrastructure.persistence.workspaces.payments.models import (
            WorkspacePaymentMethod,
        )

        normalized = (settlement_currency or "").strip().upper()
        if not normalized:
            return

        updated = WorkspacePaymentMethod.objects.filter(
            id=method_id, is_deleted=False
        ).update(settlement_currency=normalized)

        if updated == 0:
            logger.warning(
                "settlement_currency backfill skipped: method_id=%s not found",
                method_id,
            )
        else:
            logger.info(
                "settlement_currency backfilled method_id=%s currency=%s",
                method_id,
                normalized,
            )
