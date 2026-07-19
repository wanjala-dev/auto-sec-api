from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class Query:
    """Base marker for read-side queries."""

    query_id: UUID = field(default_factory=uuid4)
    correlation_id: str | None = None
