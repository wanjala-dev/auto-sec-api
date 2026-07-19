from __future__ import annotations

from django.utils import timezone

from components.payments.application.ports.payment_flow_state_port import PaymentFlowStatePort
from infrastructure.persistence.workspaces.payments.models import PaymentAttempt, PaymentOrder


class OrmPaymentFlowStateRepository(PaymentFlowStatePort):
    """Transitional adapter for payment order/attempt state transitions."""

    @staticmethod
    def _mark_order_status(
        order,
        status: str,
        message: str | None = None,
    ) -> None:
        if order is None:
            return

        order.status = status
        update_fields = ["status", "updated_at"]
        if message is not None:
            order.status_message = message
            update_fields.append("status_message")
        if status in {
            PaymentOrder.STATUS_SUCCEEDED,
            PaymentOrder.STATUS_FAILED,
            PaymentOrder.STATUS_CANCELED,
        }:
            order.completed_at = timezone.now()
            update_fields.append("completed_at")
        order.save(update_fields=update_fields)

    @staticmethod
    def _mark_attempt_status(
        attempt,
        status: str,
        message: str | None = None,
        *,
        gateway_reference: str | None = None,
        gateway_reference_type: str | None = None,
    ) -> None:
        if attempt is None:
            return

        attempt.status = status
        update_fields = ["status", "updated_at"]
        if message is not None:
            attempt.status_message = message
            update_fields.append("status_message")
        if gateway_reference:
            attempt.gateway_reference = gateway_reference
            attempt.gateway_reference_type = gateway_reference_type or ""
            update_fields.extend(["gateway_reference", "gateway_reference_type"])
        if status in {
            PaymentAttempt.STATUS_SUCCEEDED,
            PaymentAttempt.STATUS_FAILED,
            PaymentAttempt.STATUS_CANCELED,
        }:
            attempt.completed_at = timezone.now()
            update_fields.append("completed_at")
        attempt.save(update_fields=update_fields)

    def mark_processing(
        self,
        *,
        order,
        attempt,
        gateway_reference: str,
        gateway_reference_type: str,
    ) -> None:
        # Status constants are read off the CLASS, not the (possibly-None)
        # instance — _mark_*_status already no-op on None, but evaluating
        # `attempt.STATUS_*` as an argument crashes when attempt/order is None
        # (e.g. a subscription.deleted / checkout.session.expired webhook that
        # carries no PaymentOrder in its metadata). See mark_canceled.
        self._mark_attempt_status(
            attempt,
            PaymentAttempt.STATUS_PROCESSING,
            gateway_reference=gateway_reference,
            gateway_reference_type=gateway_reference_type,
        )
        self._mark_order_status(order, PaymentOrder.STATUS_PROCESSING)

    def mark_succeeded(
        self,
        *,
        order,
        attempt,
    ) -> None:
        self._mark_attempt_status(attempt, PaymentAttempt.STATUS_SUCCEEDED)
        self._mark_order_status(order, PaymentOrder.STATUS_SUCCEEDED)

    def mark_failed(
        self,
        *,
        order,
        attempt,
        message: str,
    ) -> None:
        self._mark_attempt_status(attempt, PaymentAttempt.STATUS_FAILED, message)
        self._mark_order_status(order, PaymentOrder.STATUS_FAILED, message)

    def mark_requires_action(
        self,
        *,
        order,
        attempt,
        message: str,
    ) -> None:
        self._mark_attempt_status(attempt, PaymentAttempt.STATUS_REQUIRES_ACTION, message)
        self._mark_order_status(order, PaymentOrder.STATUS_REQUIRES_ACTION, message)

    def mark_canceled(
        self,
        *,
        order,
        attempt,
        message: str,
    ) -> None:
        # order/attempt may both be None — a subscription cancellation or an
        # expired checkout session whose Stripe metadata carries no PaymentOrder.
        # The _mark_* helpers already guard None; reading the status constant off
        # the class (not the instance) is what makes this safe. Previously this
        # raised AttributeError and aborted the handler BEFORE the workspace
        # downgrade ran, so cancelled team plans never lost their paid plan.
        self._mark_attempt_status(attempt, PaymentAttempt.STATUS_CANCELED, message)
        self._mark_order_status(order, PaymentOrder.STATUS_CANCELED, message)
