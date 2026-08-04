from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuditLogListRequest:
    """Validated input for ``GET /audit/entries/``.

    Translates DRF query-params into a typed object the use case can
    consume without touching ``request`` directly. ``workspace_id`` is
    the tenant named by the caller — ``IsAuditWorkspaceMember`` has
    already proven membership on it before this DTO is built.
    """

    workspace_id: str
    entity_type: str
    object_id: str
    field_name: str | None = None
    limit: int = 50
