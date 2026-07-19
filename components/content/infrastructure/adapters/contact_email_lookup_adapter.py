"""Contact email lookup — stubbed in the auto-sec fork.

The nonprofit `contacts` context (recipient directory) is not part of the
security product, so there's nothing to resolve. Returns an empty list; the
draft AI-assist path doesn't depend on recipient-email resolution.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID


class ContactEmailLookupAdapter:
    """No-op implementation of ContactEmailLookupPort (no contacts context)."""

    def lookup(self, *, workspace_id: UUID, contact_ids: Sequence[UUID]) -> list[dict]:
        return []
