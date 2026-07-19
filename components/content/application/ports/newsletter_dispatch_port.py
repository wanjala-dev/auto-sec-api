"""Port for newsletter email dispatch.

Sends one email per recipient (no BCC blast) so each subscriber gets
their own tokenized unsubscribe link + ``List-Unsubscribe`` header
(RFC 8058 one-click unsubscribe). Gmail + Yahoo throttle bulk senders
that lack this since Feb 2024 — it's not optional for the paid surface.

Implementations:

- MUST raise on whole-batch transport failure (e.g. SMTP unreachable,
  auth error) so the caller can roll back the status transition. A
  newsletter in SENT status with no actual delivery is a silent
  integrity bug.
- MUST swallow per-recipient failures (log + increment ``failed`` on
  the summary). A single bad recipient address shouldn't block delivery
  to the other 999.
- MUST set ``List-Unsubscribe`` + ``List-Unsubscribe-Post`` headers on
  every outbound message — see RFC 8058 §4.
- MUST substitute ``{{subscriber_first_name}}`` and ``{{unsubscribe_url}}``
  in both the HTML and plain bodies before sending each copy.
- MUST inject an unsubscribe footer (HTML + plain) if the body doesn't
  already contain the ``{{unsubscribe_url}}`` token (defensive — if the
  editor body forgot the token, the footer is the legal fallback).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from components.content.domain.value_objects.dispatch_summary import DispatchSummary
from components.content.domain.value_objects.subscriber_dispatch_target import (
    SubscriberDispatchTarget,
)


class NewsletterDispatchPort(Protocol):
    def send(
        self,
        *,
        subject: str,
        html_body: str,
        plain_body: str,
        targets: Sequence[SubscriberDispatchTarget],
        sender_address: str | None = None,
        sender_name: str | None = None,
        reply_to: str | None = None,
        list_unsubscribe_base_url: str,
        list_unsubscribe_mailto: str | None = None,
        open_tokens: dict[str, str] | None = None,
    ) -> DispatchSummary:
        """Deliver one copy per target.

        ``open_tokens`` (task #25) maps recipient email → open-tracking
        token; when a recipient has one, the adapter embeds that
        recipient's tracking pixel in their HTML copy and the summary
        carries per-recipient outcome lists for the dispatch ledger.

        ``list_unsubscribe_base_url`` MUST end with ``/`` — the adapter
        builds each recipient's URL by string-concatenating the token.
        Example: ``https://app.wanjala.art/u/`` →
        ``https://app.wanjala.art/u/<token>``.

        ``list_unsubscribe_mailto`` is the optional mailto address for
        the ``List-Unsubscribe`` header second slot. SES (and many other
        ESPs) honour clicks on the inbox unsubscribe button by sending
        an empty POST to the URL OR an email to the mailto. The mailto
        gives subscribers using strict-CSP clients an out.
        """
        ...
