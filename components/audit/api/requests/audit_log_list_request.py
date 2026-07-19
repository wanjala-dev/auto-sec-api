from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuditLogListRequest:
    """Validated input for ``GET /audit/entries/``.

    Translates DRF query-params into a typed object the use case can
    consume without touching ``request`` directly.
    """

    entity_type: str
    object_id: str
    field_name: str | None = None
    limit: int = 50
