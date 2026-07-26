"""Read-side query for the materialised attack paths (CQRS read)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True)
class ListAttackPathsQuery:
    workspace_id: UUID
    category: str | None = None  # AttackPathCategory.value
    min_score: float | None = None
    limit: int = DEFAULT_LIMIT
