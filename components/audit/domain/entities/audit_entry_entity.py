"""Pure domain representation of an audit entry.

Framework-agnostic — no Django, no DRF imports. Used by application
use cases that need to reason about audit entries without coupling
to the ORM model in ``infrastructure/persistence/audit``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    """One immutable record of a tracked field change."""

    id: str
    workspace_id: str | None
    entity_type: str  # "app_label.model_name", e.g. "campaign.campaign"
    entity_id: str
    field_name: str
    previous_value: Any
    new_value: Any
    actor_id: str | None
    actor_display: str
    reason: str
    created_at: datetime
