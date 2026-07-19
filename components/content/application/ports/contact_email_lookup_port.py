"""Port: resolve workspace contacts to emailable recipients (task #20).

The content context's view of the contacts directory — just enough to
address a draft to a small, explicit set of contacts. The adapter bridges
to the contacts context's application layer (LookupContactEmailsUseCase);
content never touches contacts infrastructure.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class ContactEmailLookupPort(Protocol):
    def lookup(self, *, workspace_id: UUID, contact_ids: Sequence[UUID]) -> list[dict]:
        """Return ``[{id, name, email}]`` for the workspace's contacts that
        have an email address. Unknown ids and email-less contacts are
        silently skipped."""
        ...
