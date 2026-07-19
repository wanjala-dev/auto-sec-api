from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AuditLogEntryResource:
    """Typed projection of a single audit-log row for REST rendering.

    The DRF serializer maps this dataclass into JSON; the controller
    never reaches into the ORM row directly.
    """

    id: str
    entity_type: str
    object_id: str
    actor_id: str | None
    actor_display: str | None
    action: str
    field_name: str | None
    old_value: Any
    new_value: Any
    created_at: datetime
