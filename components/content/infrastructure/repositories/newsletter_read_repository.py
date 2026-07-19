"""ORM-backed Newsletter reads."""

from __future__ import annotations

import datetime
from typing import Sequence
from uuid import UUID

from django.db.models import Exists, OuterRef, Q

from components.content.application.ports.newsletter_reader_port import (
    NewsletterReaderPort,
)
from components.content.domain.entities.newsletter_entity import NewsletterEntity
from components.content.domain.value_objects.subscriber_dispatch_target import (
    SubscriberDispatchTarget,
)
from components.content.infrastructure.repositories.newsletter_store_repository import (
    _to_entity,
)


def _active_non_suppressed_subscribers_qs(workspace_id: UUID):
    """Return the queryset of send-eligible Subscribers for a workspace.

    Filters: ``workspace_id=X AND is_active=True AND email NOT in
    SuppressedAddress (workspace-scoped OR system-wide)``.

    Implemented as an ``EXISTS`` subquery so the suppression check runs
    in the DB (no Python-side loop), and so the same query shape can be
    used by the count + the list methods without duplication.
    """

    from infrastructure.persistence.content.models import (
        SuppressedAddress,
        Subscriber,
    )

    suppression_match = SuppressedAddress.objects.filter(
        email=OuterRef("email"),
    ).filter(
        Q(workspace_id=workspace_id) | Q(workspace__isnull=True),
    )
    return (
        Subscriber.objects
        .filter(workspace_id=workspace_id, is_active=True)
        .annotate(_is_suppressed=Exists(suppression_match))
        .filter(_is_suppressed=False)
    )


class NewsletterReadRepository(NewsletterReaderPort):
    def get(self, *, newsletter_id: UUID) -> NewsletterEntity | None:
        from infrastructure.persistence.content.models import Newsletter

        row = Newsletter.objects.filter(pk=newsletter_id).first()
        return _to_entity(row) if row else None

    def list_for_workspace(
        self,
        *,
        workspace_id: UUID,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[NewsletterEntity]:
        from infrastructure.persistence.content.models import Newsletter

        qs = Newsletter.objects.filter(workspace_id=workspace_id)
        if status:
            qs = qs.filter(status=status)
        return [_to_entity(row) for row in qs[offset : offset + limit]]

    def find_for_period(
        self,
        *,
        workspace_id: UUID,
        period_start: datetime.date,
        period_end: datetime.date,
    ) -> NewsletterEntity | None:
        from infrastructure.persistence.content.models import Newsletter

        row = (
            Newsletter.objects.filter(
                workspace_id=workspace_id,
                period_start=period_start,
                period_end=period_end,
            )
            .order_by("-created_at")
            .first()
        )
        return _to_entity(row) if row else None

    def count_workspace_dispatch_targets(self, *, workspace_id: UUID) -> int:
        return _active_non_suppressed_subscribers_qs(workspace_id).count()

    def list_workspace_dispatch_targets(
        self,
        *,
        workspace_id: UUID,
    ) -> Sequence[SubscriberDispatchTarget]:
        qs = (
            _active_non_suppressed_subscribers_qs(workspace_id)
            .only("email", "name", "unsubscribe_token")
            .order_by("email")
        )
        return [
            SubscriberDispatchTarget(
                email=row.email,
                unsubscribe_token=row.unsubscribe_token,
                name=row.name,
            )
            for row in qs.iterator(chunk_size=500)
        ]

    @staticmethod
    def _normalise_emails(emails: Sequence[str]) -> list[str]:
        # Subscriber rows store lowercased emails (see SubscriberRepository.subscribe);
        # match on the same normalisation so a segment's mixed-case addresses resolve.
        return sorted({(e or "").strip().lower() for e in emails if (e or "").strip()})

    def count_dispatch_targets_for_emails(
        self,
        *,
        workspace_id: UUID,
        emails: Sequence[str],
    ) -> int:
        normalised = self._normalise_emails(emails)
        if not normalised:
            return 0
        return (
            _active_non_suppressed_subscribers_qs(workspace_id)
            .filter(email__in=normalised)
            .count()
        )

    def list_dispatch_targets_for_emails(
        self,
        *,
        workspace_id: UUID,
        emails: Sequence[str],
    ) -> Sequence[SubscriberDispatchTarget]:
        normalised = self._normalise_emails(emails)
        if not normalised:
            return []
        qs = (
            _active_non_suppressed_subscribers_qs(workspace_id)
            .filter(email__in=normalised)
            .only("email", "name", "unsubscribe_token")
            .order_by("email")
        )
        return [
            SubscriberDispatchTarget(
                email=row.email,
                unsubscribe_token=row.unsubscribe_token,
                name=row.name,
            )
            for row in qs.iterator(chunk_size=500)
        ]

    # Legacy passthrough kept transiently for back-compat — see port
    # docstring for the removal plan.
    def list_subscriber_emails(
        self,
        *,
        newsletter_id: UUID,
    ) -> Sequence[str]:
        from infrastructure.persistence.content.models import Newsletter

        try:
            row = Newsletter.objects.get(pk=newsletter_id)
        except Newsletter.DoesNotExist:
            return []
        return list(row.subscribers.values_list("email", flat=True))
