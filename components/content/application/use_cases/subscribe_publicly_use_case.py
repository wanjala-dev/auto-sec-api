"""Use case: public, unauthenticated subscribe to a workspace newsletter.

Reached via ``POST /content/public/<workspace_id>/subscribe/`` from the
sponsor profile widget, the marketing site, or any embeddable form. The
endpoint is rate-limited but un-authenticated by design.

Behaviour:

- Always succeeds from the client's perspective (returns 202 either way)
  to avoid email-enumeration attacks. Whether the result was a new
  subscriber, a re-subscriber, an already-confirmed subscriber, or a
  silently-suppressed address is not exposed in the response.
- ``require_confirmation`` is True when the workspace preference
  ``double_opt_in_enabled`` is set. In that case the new row is
  inserted at ``is_active=False, confirmed_at=None`` and a confirmation
  email is dispatched out-of-band. Single-opt-in is the default for
  Wanjala's East Africa ICP since GDPR exposure is limited; workspaces
  with EU subscribers flip the toggle on their preference page.
- Source on the new row is ``self_subscribed`` so the analytics surface
  can distinguish self-signups from admin imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.content.application.ports.subscriber_store_port import (
    SubscriberStorePort,
)
from components.content.domain.enums import SubscriberSource


@dataclass
class SubscribePubliclyUseCase:
    subscriber_store: SubscriberStorePort

    def execute(
        self,
        *,
        workspace_id: UUID,
        email: str,
        name: str = "",
        require_confirmation: bool = False,
    ) -> tuple[UUID, bool]:
        """Returns ``(unsubscribe_token, was_newly_created)``.

        Token is used by the caller to dispatch the confirmation email
        (if double-opt-in is on) — otherwise the caller discards it.
        """

        return self.subscriber_store.subscribe(
            workspace_id=workspace_id,
            email=email,
            name=name,
            source=SubscriberSource.SELF_SUBSCRIBED,
            require_confirmation=require_confirmation,
        )
