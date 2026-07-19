"""Use case: confirm a self-subscribed subscriber via their token.

Reached via ``POST /content/public/confirm/<token>/`` from the
confirmation email link. Flips the matching subscriber row to
``is_active=True, confirmed_at=now()``. Idempotent — clicking the link
twice doesn't double-stamp.

Returns False if the token doesn't match any row (expired-link UX:
landing page should say "this link is no longer valid").
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.content.application.ports.subscriber_store_port import (
    SubscriberStorePort,
)


@dataclass
class ConfirmSubscriptionUseCase:
    subscriber_store: SubscriberStorePort

    def execute(self, *, token: UUID) -> bool:
        return self.subscriber_store.confirm_by_token(token=token)
