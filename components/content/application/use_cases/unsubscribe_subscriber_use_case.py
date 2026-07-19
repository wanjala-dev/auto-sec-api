"""Use case: unsubscribe a subscriber via their token.

Reached two ways:

- ``POST /content/public/unsubscribe/<token>/`` from the FE landing page
  (humans clicking the link in an email).
- ``POST {list_unsubscribe_url}`` from email-client one-click handlers
  (Gmail, Yahoo, Apple Mail) — RFC 8058 ``List-Unsubscribe-Post`` flow.

Either path soft-deletes (``is_active=False, unsubscribed_at=now()``);
the row stays so the same token resolves on subsequent retries.

Returns False if the token doesn't match any row — the controller maps
that to a 200 with a "this link is no longer valid" landing page so
spammy bots can't enumerate which tokens are real.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.content.application.ports.subscriber_store_port import (
    SubscriberStorePort,
)


@dataclass
class UnsubscribeSubscriberUseCase:
    subscriber_store: SubscriberStorePort

    def execute(self, *, token: UUID) -> bool:
        return self.subscriber_store.unsubscribe_by_token(token=token)
