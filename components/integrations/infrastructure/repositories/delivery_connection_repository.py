"""Resolve and stamp :class:`DeliveryConnection` rows (ADR 0016 D2).

Owns the two ORM concerns the adapters must not carry: turning a stored row into
a secret-decrypted :class:`ResolvedDeliveryConnection`, and stamping health after
an attempt. Keeping this here is what lets a delivery adapter be pure I/O and lets
a second provider (Teams, SMTP) reuse resolution untouched.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from components.integrations.application.ports.delivery_channel_port import ResolvedDeliveryConnection
from components.integrations.application.providers.secret_envelope_provider import (
    decrypt_secret,
    get_secret_decryption_error,
)

logger = logging.getLogger(__name__)

_ERROR_MAX_CHARS = 2000


class DeliveryConnectionRepository:
    """Reads connections for delivery and records the outcome."""

    def enabled_for_workspace(self, workspace_id: UUID, *, kind: str | None = None) -> list[ResolvedDeliveryConnection]:
        """Every enabled, non-errored connection for the workspace, secrets decrypted.

        A row whose secret cannot be decrypted is skipped and logged, never returned
        half-formed — a `SECRET_KEY` rotation makes stored envelopes unreadable, and a
        connection we cannot authenticate is not a connection we should try to use.
        """
        from infrastructure.persistence.integrations.models import DeliveryConnection

        rows = DeliveryConnection.objects.filter(workspace_id=workspace_id, is_enabled=True)
        if kind:
            rows = rows.filter(kind=kind)

        resolved: list[ResolvedDeliveryConnection] = []
        for row in rows.iterator(chunk_size=100):
            try:
                secret = decrypt_secret(row.secret_ciphertext)
            except get_secret_decryption_error():
                logger.exception("delivery_connection_secret_decrypt_failed connection_id=%s", row.id)
                continue
            if not secret:
                logger.warning("delivery_connection_missing_secret connection_id=%s", row.id)
                continue
            resolved.append(self._to_resolved(row, secret))
        return resolved

    def get_resolved(self, connection_id: UUID) -> ResolvedDeliveryConnection | None:
        """One connection by id, secret decrypted. None when missing or undecryptable."""
        from infrastructure.persistence.integrations.models import DeliveryConnection

        row = DeliveryConnection.objects.filter(id=connection_id).first()
        if row is None:
            return None
        try:
            secret = decrypt_secret(row.secret_ciphertext)
        except get_secret_decryption_error():
            logger.exception("delivery_connection_secret_decrypt_failed connection_id=%s", connection_id)
            return None
        if not secret:
            return None
        return self._to_resolved(row, secret)

    def mark_delivered(self, connection_id: UUID) -> None:
        from infrastructure.persistence.integrations.models import DeliveryConnection

        DeliveryConnection.objects.filter(id=connection_id).update(
            last_delivery_at=datetime.now(UTC),
            last_error="",
            status=DeliveryConnection.Status.CONNECTED,
        )

    def mark_error(self, connection_id: UUID, error: str) -> None:
        """Record a failure. Does NOT disable the connection — sustained-failure
        auto-disable is a deliberate P2 decision (ADR 0016 D7), not a side effect
        of one bad response."""
        from infrastructure.persistence.integrations.models import DeliveryConnection

        DeliveryConnection.objects.filter(id=connection_id).update(
            last_error=(error or "")[:_ERROR_MAX_CHARS],
            status=DeliveryConnection.Status.ERROR,
        )

    def mark_verified(self, connection_id: UUID, *, ok: bool, detail: str = "") -> None:
        from infrastructure.persistence.integrations.models import DeliveryConnection

        DeliveryConnection.objects.filter(id=connection_id).update(
            last_verified_at=datetime.now(UTC),
            last_error="" if ok else (detail or "")[:_ERROR_MAX_CHARS],
            status=DeliveryConnection.Status.CONNECTED if ok else DeliveryConnection.Status.ERROR,
        )

    @staticmethod
    def _to_resolved(row, secret: str) -> ResolvedDeliveryConnection:
        config = row.config or {}
        return ResolvedDeliveryConnection(
            id=row.id,
            kind=row.kind,
            auth_mode=row.auth_mode,
            secret=secret,
            name=row.name or "",
            channel=str(config.get("channel") or ""),
            min_severity=row.min_severity,
            events=tuple(row.events or ()),
        )
