from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TrashCommand:
    workspace_id: UUID
    entity_type: str
    # Cast to str by the controller so the use case + adapters can
    # handle both UUID and integer PKs uniformly.
    entity_id: str
    deleted_by: UUID
    # Optional human-readable justification surfaced from the UI
    # delete confirmation. Empty string when no reason was supplied —
    # the audit row still records the actor + timestamp so we can
    # always answer "who" and "when," even when "why" is missing.
    reason: str = ""
