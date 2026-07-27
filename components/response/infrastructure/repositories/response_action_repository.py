"""Django repository implementing ResponseActionStorePort."""

from __future__ import annotations

from uuid import UUID

from components.response.application.ports.response_action_store_port import (
    ResponseActionStorePort,
)
from components.response.domain.entities.response_action_entity import ResponseActionExecution
from components.response.mappers.db.response_action_mapper import to_entity, to_row_fields


class DjangoResponseActionRepository(ResponseActionStorePort):
    def save(self, action: ResponseActionExecution) -> ResponseActionExecution:
        from infrastructure.persistence.response.models import ResponseActionExecution as Row

        row, _ = Row.objects.update_or_create(
            id=action.id,
            defaults={"workspace_id": action.workspace_id, **to_row_fields(action)},
        )
        return to_entity(row)

    def get(self, action_id: UUID, *, workspace_id: UUID) -> ResponseActionExecution | None:
        from infrastructure.persistence.response.models import ResponseActionExecution as Row

        row = Row.objects.select_related("workspace").filter(id=action_id, workspace_id=workspace_id).first()
        return to_entity(row) if row is not None else None

    def list_for_workspace(
        self, workspace_id: UUID, *, status: str | None = None, limit: int = 50
    ) -> list[ResponseActionExecution]:
        from infrastructure.persistence.response.models import ResponseActionExecution as Row

        qs = Row.objects.select_related("workspace").filter(workspace_id=workspace_id)
        if status:
            qs = qs.filter(status=status)
        return [to_entity(row) for row in qs.order_by("-requested_at")[:limit]]
