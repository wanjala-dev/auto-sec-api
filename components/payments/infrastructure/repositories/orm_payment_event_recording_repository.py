from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction

from components.payments.mappers.db.payment_event_mapper import to_payment_event_entity
from components.payments.application.ports.payment_event_recording_port import (
    PaymentEventRecordingPort,
    RecordedPaymentEvent,
)
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.workspaces.payments.models import PaymentEvent, WorkspacePaymentMethod


class OrmPaymentEventRecordingRepository(PaymentEventRecordingPort):
    """Transitional adapter for idempotent payment-event persistence."""

    @staticmethod
    def _hash_payload(payload: dict[str, Any] | None) -> str:
        if not payload:
            return ""
        try:
            normalized = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        except Exception:
            return ""
        return hashlib.sha256(normalized).hexdigest()

    @staticmethod
    def _find_existing_event(
        *,
        queryset,
        provider_key: str,
        provider_event_id: str,
        external_id: str,
        event_type_key: str,
    ):
        existing = None
        if provider_event_id:
            existing = queryset.filter(
                provider__iexact=provider_key,
                event_id=provider_event_id,
            ).first()
        if not existing and external_id and event_type_key:
            existing = queryset.filter(
                provider__iexact=provider_key,
                external_id=external_id,
                event_type__iexact=event_type_key,
            ).first()
        return existing

    @staticmethod
    def _resolve_workspace(*, method_id: UUID | None, workspace_id: UUID | None):
        method = (
            WorkspacePaymentMethod.objects.filter(id=method_id).select_related("workspace").first()
            if method_id
            else None
        )
        workspace = method.workspace if method else None
        if not workspace and workspace_id:
            workspace = Workspace.objects.filter(id=workspace_id).first()
        return method, workspace

    def record_if_new(
        self,
        *,
        provider: str,
        provider_account_id: str | None,
        provider_event_id: str,
        external_id: str | None,
        event_type: str,
        workspace_id: UUID | None,
        method_id: UUID | None,
        amount: Decimal | None,
        currency: str | None,
        payload: dict[str, Any] | None,
    ) -> RecordedPaymentEvent:
        if not (provider_event_id or external_id):
            return RecordedPaymentEvent(record=None, is_new=False)

        method, workspace = self._resolve_workspace(method_id=method_id, workspace_id=workspace_id)
        provider_key = (provider or "").lower()
        event_type_key = (event_type or "").lower()
        external_key = external_id or ""
        payload_hash = self._hash_payload(payload)

        db_alias = PaymentEvent.objects.db
        queryset = PaymentEvent.objects.using(db_alias)

        with transaction.atomic(using=db_alias):
            existing = self._find_existing_event(
                queryset=queryset,
                provider_key=provider_key,
                provider_event_id=provider_event_id,
                external_id=external_key,
                event_type_key=event_type_key,
            )
            if existing:
                return RecordedPaymentEvent(
                    record=to_payment_event_entity(existing),
                    is_new=False,
                )

            record_id = uuid4()
            queryset.bulk_create(
                [
                    PaymentEvent(
                        id=record_id,
                        provider=provider_key,
                        provider_account_id=provider_account_id or "",
                        workspace=workspace,
                        method=method,
                        event_id=provider_event_id or "",
                        external_id=external_key,
                        event_type=event_type or "",
                        amount=amount,
                        currency=(currency or "").lower(),
                        payload=payload or {},
                        payload_hash=payload_hash,
                    )
                ],
                ignore_conflicts=True,
            )

            created = queryset.filter(id=record_id).first()
            if created:
                return RecordedPaymentEvent(
                    record=to_payment_event_entity(created),
                    is_new=True,
                )

            existing = self._find_existing_event(
                queryset=queryset,
                provider_key=provider_key,
                provider_event_id=provider_event_id,
                external_id=external_key,
                event_type_key=event_type_key,
            )
            if existing:
                return RecordedPaymentEvent(
                    record=to_payment_event_entity(existing),
                    is_new=False,
                )

        return RecordedPaymentEvent(record=None, is_new=False)
