from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AggregateId:
    """Stable identifier wrapper for aggregate roots."""

    value: UUID
