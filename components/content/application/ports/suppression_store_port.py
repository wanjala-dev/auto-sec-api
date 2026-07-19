"""Port for SuppressedAddress writes.

Populated by the SES SNS bounce/complaint handler + admin-remove action.
The dispatch adapter reads the table via the EXISTS subquery in
``NewsletterReadRepository._active_non_suppressed_subscribers_qs``;
it never calls a method on this port.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class SuppressionStorePort(Protocol):
    def suppress(
        self,
        *,
        workspace_id: UUID | None,
        email: str,
        reason: str,
        source_event: dict[str, Any] | None = None,
    ) -> bool:
        """Add the email to the suppression list.

        ``workspace_id=None`` means system-wide (e.g., a permanently
        invalid address from a hard bounce). Per-workspace rows only
        block sends from that workspace; the system-wide row blocks
        every workspace.

        Returns True if a new row was inserted, False if the
        ``(workspace, email)`` (or ``(NULL, email)``) combination was
        already suppressed. Idempotent: SES retries the same SNS
        notification on transient delivery failure, so the handler must
        not double-count.

        ``source_event`` is the raw SNS notification body (or admin
        action context) for audit.
        """
        ...
