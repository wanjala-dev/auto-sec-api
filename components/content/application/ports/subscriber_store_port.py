"""Port for Subscriber writes — subscribe, confirm, unsubscribe, mark-suppressed."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class SubscriberStorePort(Protocol):
    def subscribe(
        self,
        *,
        workspace_id: UUID,
        email: str,
        name: str,
        source: str,
        require_confirmation: bool,
    ) -> tuple[UUID, bool]:
        """Idempotently subscribe an email to a workspace.

        Returns ``(unsubscribe_token, was_created)``. ``was_created=True``
        means a new row was inserted; ``False`` means the row already
        existed (matched by ``(workspace, email)``). The unsubscribe
        token is the existing row's token in the duplicate case — that
        way the subscriber's old unsubscribe links keep working.

        When ``require_confirmation=True``, the new row starts at
        ``is_active=False, confirmed_at=None`` so dispatching skips it
        until the confirmation endpoint flips it.

        If the row is currently suppressed (matching SuppressedAddress),
        this method does NOT unsuppress — the caller's responsibility to
        check upstream. Subscribing a suppressed address creates the
        Subscriber row but the dispatch adapter will still skip it
        because the suppression check wins.

        Idempotency rationale: the public endpoint always returns 202 to
        avoid email enumeration, so the same email POSTing twice in a
        row must be safe.
        """
        ...

    def confirm_by_token(self, *, token: UUID) -> bool:
        """Mark the subscriber row matching ``token`` as confirmed +
        active. Returns True on success, False if no row matched.

        Idempotent: re-confirming an already-confirmed row is a no-op."""
        ...

    def unsubscribe_by_token(self, *, token: UUID) -> bool:
        """Mark the subscriber row matching ``token`` as inactive +
        unsubscribed. Returns True on success, False if no row matched.

        Soft-delete only — the row stays so the unsubscribe link from
        old emails keeps resolving. Idempotent on repeat: clicking
        twice doesn't change the unsubscribed_at after the first call.
        """
        ...

    def soft_remove_by_email(
        self,
        *,
        workspace_id: UUID,
        email: str,
    ) -> bool:
        """Admin-initiated remove — same soft-delete as unsubscribe, but
        scoped to a (workspace, email) lookup since the admin UI doesn't
        know the token. Returns True on success.
        """
        ...

    def enroll_from_directory(
        self,
        *,
        workspace_id: UUID,
        email: str,
        name: str,
    ) -> str:
        """Add a directory contact to the newsletter list — create-only,
        never resurrect an opt-out.

        Unlike ``subscribe`` (which reactivates an unsubscribed row so a
        returning self-subscriber gets re-added), this is for the admin
        bulk "add these contacts to my list" action, where re-adding
        someone who explicitly unsubscribed would violate their opt-out.
        So it ONLY inserts when no row exists; an existing row — active or
        unsubscribed — is left exactly as-is. New rows are active with
        ``source=directory_picked`` and carry a working unsubscribe token.

        Returns one of: ``"added"`` (new active row created),
        ``"already_subscribed"`` (an active row already existed), or
        ``"skipped_unsubscribed"`` (a row exists but is unsubscribed — left
        untouched, the contact is NOT emailed). Suppression is enforced
        separately at dispatch time.
        """
        ...
