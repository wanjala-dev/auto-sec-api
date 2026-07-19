"""ORM-backed implementation of SubscriberStorePort.

Uses atomic ``UPDATE WHERE`` queries (no ``select_for_update``) so the
methods work under Django's multi-DB tenant routing without requiring
the caller to wrap them in a ``transaction.atomic(using=…)`` block
matching whatever DB Subscriber is routed to. The rowcount on the
UPDATE acts as the "did anything change" signal — race-safe enough for
the public compliance loop (Gmail/Yahoo retry tolerant; SES SNS
retries on transient failure).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from django.db import IntegrityError
from django.utils import timezone

from components.content.application.ports.subscriber_store_port import (
    SubscriberStorePort,
)


class SubscriberRepository(SubscriberStorePort):
    def subscribe(
        self,
        *,
        workspace_id: UUID,
        email: str,
        name: str,
        source: str,
        require_confirmation: bool,
    ) -> tuple[UUID, bool]:
        from infrastructure.persistence.content.models import Subscriber

        normalised_email = email.strip().lower()
        now = timezone.now()

        # Existing row? Reactivate if previously unsubscribed; re-confirm
        # if the workspace flipped on double-opt-in.
        existing = Subscriber.objects.filter(
            workspace_id=workspace_id,
            email=normalised_email,
        ).only("unsubscribe_token", "is_active", "confirmed_at").first()
        if existing is not None:
            updates: dict = {}
            if not existing.is_active:
                updates["is_active"] = not require_confirmation
                updates["unsubscribed_at"] = None
            if not require_confirmation and existing.confirmed_at is None:
                updates["confirmed_at"] = now
            if updates:
                Subscriber.objects.filter(pk=existing.pk).update(**updates)
            return existing.unsubscribe_token, False

        new_token = uuid4()
        try:
            Subscriber.objects.create(
                workspace_id=workspace_id,
                email=normalised_email,
                name=name.strip(),
                source=source,
                is_active=not require_confirmation,
                confirmed_at=None if require_confirmation else now,
                unsubscribe_token=new_token,
            )
        except IntegrityError:
            # Race: a concurrent request created the row between our
            # SELECT and INSERT. Re-read + return the existing token.
            existing = Subscriber.objects.filter(
                workspace_id=workspace_id,
                email=normalised_email,
            ).only("unsubscribe_token").first()
            if existing is not None:
                return existing.unsubscribe_token, False
            raise
        return new_token, True

    def confirm_by_token(self, *, token: UUID) -> bool:
        """Idempotent confirm. Returns True when a row matched the token
        (regardless of whether it was already confirmed)."""

        from infrastructure.persistence.content.models import Subscriber

        # Conditional update — only sets confirmed_at if NULL so repeat
        # clicks don't overwrite the timestamp; activates the row in
        # either case so an unsubscribed-then-reconfirmed row reactivates.
        now = timezone.now()
        Subscriber.objects.filter(
            unsubscribe_token=token, confirmed_at__isnull=True
        ).update(confirmed_at=now)
        rows = Subscriber.objects.filter(unsubscribe_token=token).update(
            is_active=True,
            unsubscribed_at=None,
        )
        return rows > 0

    def unsubscribe_by_token(self, *, token: UUID) -> bool:
        """Idempotent unsubscribe. Returns True when a row matched the
        token (regardless of whether it was already inactive)."""

        from infrastructure.persistence.content.models import Subscriber

        now = timezone.now()
        # Only stamps unsubscribed_at on rows currently active so a
        # second click doesn't move the timestamp forward.
        Subscriber.objects.filter(
            unsubscribe_token=token, is_active=True
        ).update(is_active=False, unsubscribed_at=now)
        # Existence probe — we want True when the token resolves to a
        # row even if it was already unsubscribed (idempotent UX).
        return Subscriber.objects.filter(unsubscribe_token=token).exists()

    def soft_remove_by_email(
        self,
        *,
        workspace_id: UUID,
        email: str,
    ) -> bool:
        from infrastructure.persistence.content.models import Subscriber

        normalised_email = email.strip().lower()
        now = timezone.now()
        Subscriber.objects.filter(
            workspace_id=workspace_id,
            email=normalised_email,
            is_active=True,
        ).update(is_active=False, unsubscribed_at=now)
        return Subscriber.objects.filter(
            workspace_id=workspace_id, email=normalised_email
        ).exists()

    def enroll_from_directory(
        self,
        *,
        workspace_id: UUID,
        email: str,
        name: str,
    ) -> str:
        from infrastructure.persistence.content.models import Subscriber

        from components.content.domain.enums import SubscriberSource

        normalised_email = email.strip().lower()

        existing = (
            Subscriber.objects.filter(workspace_id=workspace_id, email=normalised_email)
            .only("is_active")
            .first()
        )
        if existing is not None:
            # Never resurrect an explicit opt-out — an admin re-adding an
            # unsubscribed contact must not override their unsubscribe.
            return "already_subscribed" if existing.is_active else "skipped_unsubscribed"

        now = timezone.now()
        try:
            Subscriber.objects.create(
                workspace_id=workspace_id,
                email=normalised_email,
                name=name.strip(),
                source=SubscriberSource.DIRECTORY_PICKED,
                is_active=True,
                confirmed_at=now,
                unsubscribe_token=uuid4(),
            )
        except IntegrityError:
            # Race: a concurrent insert created the row. Re-read to classify.
            existing = (
                Subscriber.objects.filter(workspace_id=workspace_id, email=normalised_email)
                .only("is_active")
                .first()
            )
            if existing is None:
                raise
            return "already_subscribed" if existing.is_active else "skipped_unsubscribed"
        return "added"
