"""Per-recipient context the dispatch adapter needs to send one copy.

The dispatch port returns one of these per active subscriber rather than
a plain list of email strings — the adapter needs the per-recipient
``unsubscribe_token`` (to build the tokenized footer link + the RFC 8058
``List-Unsubscribe`` header) and the recipient's name (for
``{{subscriber_first_name}}`` substitution).

This is a frozen domain value object so it can flow across layers
(repository → use case → adapter) without leaking ORM model objects
into the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class SubscriberDispatchTarget:
    """One recipient's send-time context.

    Attributes:
        email: Subscriber's email address. Lowercased + trimmed at
            repository boundary — adapter trusts the format.
        unsubscribe_token: UUID embedded in the per-recipient
            unsubscribe URL and the ``List-Unsubscribe`` header. Each
            subscriber has a unique token from the moment they're
            inserted (see migration 0006); the token survives unsubscribe
            so old emails still resolve the correct row.
        name: Full display name (may be empty for self-subscribed rows
            that didn't provide one).
    """

    email: str
    unsubscribe_token: UUID
    name: str = ""

    def first_name(self) -> str:
        """Best-effort first-name extraction for ``{{subscriber_first_name}}``.

        Falls back to empty string if there's no name on the subscriber
        row — the dispatch adapter's template substitution treats empty
        as "render nothing for this token" rather than "render the
        literal {{subscriber_first_name}}".
        """

        stripped = self.name.strip()
        if not stripped:
            return ""
        # Take everything up to the first whitespace. Handles "Jane",
        # "Jane Doe", "Jane Q. Public", "Jane-Marie Doe" the same way.
        return stripped.split()[0]
