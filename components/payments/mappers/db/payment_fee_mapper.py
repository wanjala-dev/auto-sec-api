from __future__ import annotations

from components.payments.domain.entities.payment_fee_entity import PaymentFeeEntity


def fee_orm_to_entity(row) -> PaymentFeeEntity:
    return PaymentFeeEntity(
        id=row.id,
        transaction_id=row.transaction_id,
        method_id=row.method_id,
        provider=row.provider,
        context=row.context,
        fee_amount=row.fee_amount,
        currency=row.currency,
        fee_percentage=row.fee_percentage,
        fixed_fee=row.fixed_fee,
        capped_fee=row.capped_fee,
        sales_tax_amount=row.sales_tax_amount,
        sales_tax_percentage=row.sales_tax_percentage,
        metadata=row.metadata or {},
    )
