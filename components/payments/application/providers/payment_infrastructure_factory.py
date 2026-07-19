"""Cross-context factory for payment infrastructure adapters.

Other bounded contexts (e.g. sponsorship) that need to wire payment
infrastructure adapters in their composition roots should import from
this factory — **never** directly from ``components.payments.infrastructure``.

This keeps the cross-context coupling at the application-layer boundary,
making it visible and auditable in a single file.
"""

from __future__ import annotations


class PaymentInfrastructureFactory:
    """Factory that exposes payment infrastructure adapters for cross-context use.

    Each static method lazy-imports and returns the concrete adapter,
    keeping the import surface explicit and contained.
    """

    @staticmethod
    def build_payment_transaction_repository():
        """Return an ``OrmPaymentTransactionRepository`` instance."""
        from components.payments.infrastructure.repositories.orm_payment_transaction_repository import (
            OrmPaymentTransactionRepository,
        )
        return OrmPaymentTransactionRepository()

    @staticmethod
    def build_capture_recording_repository():
        """Return a ``PaymentCaptureRecordingRepository`` instance."""
        from components.payments.infrastructure.repositories.payment_capture_recording_repository import (
            PaymentCaptureRecordingRepository,
        )
        return PaymentCaptureRecordingRepository()

    @staticmethod
    def parse_bitpay_event(raw_body, headers=None):
        """Delegate to the bitpay webhook parser."""
        from components.payments.infrastructure.gateways.bitpay_webhook_parser import (
            parse_bitpay_event as _parse,
        )
        return _parse(raw_body, headers)

    @staticmethod
    def mark_payment_event_processed(payment_event, status, message=None):
        """Mark a payment event as processed (delegates to infrastructure)."""
        from components.payments.infrastructure.adapters.payment_event_state import (
            mark_payment_event_processed as _mark,
        )
        return _mark(payment_event, status, message)

    @staticmethod
    def mark_payment_event_processing(payment_event, message=None):
        """Mark a payment event as currently processing."""
        from components.payments.infrastructure.adapters.payment_event_state import (
            mark_payment_event_processing as _mark,
        )
        return _mark(payment_event, message)

    @staticmethod
    def claim_payment_event_processing(payment_event, message=None):
        """Atomically claim a payment event for processing."""
        from components.payments.infrastructure.adapters.payment_event_state import (
            claim_payment_event_processing as _claim,
        )
        return _claim(payment_event, message)

    @staticmethod
    def payment_event_is_processable(payment_event):
        """Check if a payment event can be processed."""
        from components.payments.infrastructure.adapters.payment_event_state import (
            payment_event_is_processable_for_worker,
        )
        return payment_event_is_processable_for_worker(payment_event)

    @staticmethod
    def get_bitpay_event_parser():
        """Return the ``parse_bitpay_event`` callable for injection."""
        from components.payments.infrastructure.gateways.bitpay_webhook_parser import (
            parse_bitpay_event,
        )
        return parse_bitpay_event
