"""ORM-backed implementation of SuppressionStorePort."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import IntegrityError

from components.content.application.ports.suppression_store_port import (
    SuppressionStorePort,
)


class SuppressionRepository(SuppressionStorePort):
    def suppress(
        self,
        *,
        workspace_id: UUID | None,
        email: str,
        reason: str,
        source_event: dict[str, Any] | None = None,
    ) -> bool:
        """Idempotent insert. Returns True if a new row landed, False if
        the (workspace, email) suppression already existed.

        Skips ``transaction.atomic()`` so the method works under Django's
        multi-DB tenant routing without forcing the caller to wrap it in
        a ``using=`` block matching whatever DB SuppressedAddress is
        routed to. The IntegrityError catch is sufficient for the race
        — SES SNS retries on transient delivery failure, so two
        concurrent attempts to suppress the same address only land one
        row and the second returns False cleanly.
        """

        from infrastructure.persistence.content.models import SuppressedAddress

        normalised_email = email.strip().lower()
        existing = SuppressedAddress.objects.filter(
            workspace_id=workspace_id,
            email=normalised_email,
        ).only("id").first()
        if existing is not None:
            return False
        try:
            SuppressedAddress.objects.create(
                workspace_id=workspace_id,
                email=normalised_email,
                reason=reason,
                source_event=source_event or {},
            )
        except IntegrityError:
            return False
        return True
