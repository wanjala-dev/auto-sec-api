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
    """Reads connections for delivery, serves CRUD, and records health.

    One repository per concern (the connection), not one per caller — the delivery
    path and the Settings CRUD path read the same rows, and splitting them would be
    the second parallel implementation `dry-reuse.md` §4 forbids. Delivery gets
    secret-decrypted DTOs; CRUD gets ORM rows the resource layer renders.
    """

    # ── CRUD (Settings panel) ──────────────────────────────────────────────

    def list_for_workspace(self, workspace_id) -> list:
        from infrastructure.persistence.integrations.models import DeliveryConnection

        return list(DeliveryConnection.objects.filter(workspace_id=workspace_id).order_by("kind", "created_at"))

    def get(self, workspace_id, connection_id):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        return DeliveryConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()

    def create(
        self,
        *,
        workspace_id,
        kind: str,
        name: str,
        auth_mode: str,
        secret_ciphertext: str,
        config: dict,
        min_severity: str,
        events: list,
        created_by_id=None,
    ):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        return DeliveryConnection.objects.create(
            workspace_id=workspace_id,
            kind=kind,
            name=name,
            auth_mode=auth_mode,
            secret_ciphertext=secret_ciphertext,
            config=config or {},
            min_severity=min_severity,
            events=events,
            created_by_id=created_by_id,
            status=DeliveryConnection.Status.CONNECTED,
        )

    def update(
        self,
        connection,
        *,
        name=None,
        auth_mode=None,
        secret_ciphertext=None,
        config=None,
        min_severity=None,
        events=None,
        status=None,
        is_enabled=None,
    ):
        """Partial update — only fields explicitly provided are written."""
        changed: list[str] = []

        def apply(field: str, value) -> None:
            if value is not None and getattr(connection, field) != value:
                setattr(connection, field, value)
                changed.append(field)

        apply("name", name)
        apply("auth_mode", auth_mode)
        apply("secret_ciphertext", secret_ciphertext)
        apply("config", config)
        apply("min_severity", min_severity)
        apply("events", events)
        apply("status", status)
        apply("is_enabled", is_enabled)

        if secret_ciphertext is not None:
            # A rotated credential invalidates the previous verification — the panel
            # must show "needs verifying" rather than a stale green tick.
            connection.last_verified_at = None
            connection.last_error = ""
            changed.extend(["last_verified_at", "last_error"])

        if changed:
            connection.save(update_fields=[*changed, "updated_at"])
        return connection

    def delete(self, connection) -> None:
        connection.delete()

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

    # ── Health stamping ────────────────────────────────────────────────────
    #
    # All three take an id, because the delivery path holds a secret-decrypted DTO
    # rather than an ORM row. They return the refreshed row so the verify endpoint
    # can render the outcome without a second read.

    def mark_delivered(self, connection_id: UUID):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        DeliveryConnection.objects.filter(id=connection_id).update(
            last_delivery_at=datetime.now(UTC),
            last_error="",
            status=DeliveryConnection.Status.CONNECTED,
        )
        return DeliveryConnection.objects.filter(id=connection_id).first()

    def mark_error(self, connection_id: UUID, error: str):
        """Record a failure. Does NOT disable the connection — sustained-failure
        auto-disable is a deliberate P2 decision (ADR 0016 D7), not a side effect
        of one bad response."""
        from infrastructure.persistence.integrations.models import DeliveryConnection

        DeliveryConnection.objects.filter(id=connection_id).update(
            last_error=(error or "")[:_ERROR_MAX_CHARS],
            status=DeliveryConnection.Status.ERROR,
        )
        return DeliveryConnection.objects.filter(id=connection_id).first()

    def mark_verified(self, connection_id: UUID, *, ok: bool = True, detail: str = ""):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        DeliveryConnection.objects.filter(id=connection_id).update(
            last_verified_at=datetime.now(UTC),
            last_error="" if ok else (detail or "")[:_ERROR_MAX_CHARS],
            status=DeliveryConnection.Status.CONNECTED if ok else DeliveryConnection.Status.ERROR,
        )
        return DeliveryConnection.objects.filter(id=connection_id).first()

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
