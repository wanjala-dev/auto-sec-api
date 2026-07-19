"""Resolves the fee-recording context for a PaymentSucceeded event.

Reads the ``PaymentEvent`` the event points at, ties it to the succeeded
``PaymentTransaction`` (the row ``PaymentFee`` attaches to), and gathers the
workspace's monetization mode + Connect identifiers needed to record the
revenue-share fee idempotently.
"""
from __future__ import annotations

from uuid import UUID

from components.payments.application.ports.fee_recording_context_port import (
    FeeRecordingContext,
)
from infrastructure.persistence.workspaces.payments.models import (
    PaymentEvent,
    PaymentFee,
    PaymentTransaction,
)


class OrmFeeRecordingContextRepository:
    def resolve(self, *, payment_event_id: UUID) -> FeeRecordingContext | None:
        event = (
            PaymentEvent.objects.filter(id=payment_event_id)
            .select_related("workspace", "method")
            .first()
        )
        if event is None:
            return None

        # The PaymentFee attaches to a PaymentTransaction, not the budgeting
        # Transaction. The donation capture path records one per gift, linked
        # to this PaymentEvent. Pin to a SUCCEEDED row explicitly so a
        # failed+succeeded pair on the same event can never attach the fee to
        # the failed row (a fee only exists on a settled charge).
        txn = (
            PaymentTransaction.objects.filter(
                payment_event_id=payment_event_id,
                status=PaymentTransaction.STATUS_SUCCEEDED,
            )
            .order_by("-created_at")
            .first()
        )
        if txn is None:
            return None

        method = event.method
        if method is None:
            return None

        workspace = event.workspace
        monetization_mode = getattr(workspace, "donation_monetization", "") or ""
        revenue_share_bps = int(getattr(workspace, "revenue_share_bps", 0) or 0)

        # Connect identifiers for the one-time fee lookup. payment_intent lives
        # on the checkout.session.completed payload object; the account is on
        # the event row.
        payload = event.payload or {}
        obj = payload.get("data", {}).get("object", {}) if isinstance(payload, dict) else {}
        payment_intent_id = ""
        if isinstance(obj, dict):
            pi = obj.get("payment_intent")
            if isinstance(pi, str):
                payment_intent_id = pi
            elif isinstance(pi, dict):
                payment_intent_id = pi.get("id") or ""

        fee_already_recorded = PaymentFee.objects.filter(transaction_id=txn.id).exists()

        return FeeRecordingContext(
            payment_transaction_id=txn.id,
            method_id=method.id,
            workspace_id=workspace.id if workspace is not None else None,
            provider=event.provider or "stripe",
            currency=(event.currency or txn.currency or "USD"),
            monetization_mode=monetization_mode,
            revenue_share_bps=revenue_share_bps,
            payment_intent_id=payment_intent_id,
            stripe_account_id=event.provider_account_id or "",
            fee_already_recorded=fee_already_recorded,
        )
