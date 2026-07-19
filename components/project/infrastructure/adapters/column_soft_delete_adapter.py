from __future__ import annotations

import logging

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort
from components.project.infrastructure.adapters.task_soft_delete_adapter import (
    PRE_TRASH_STATUS_KEY,
)

logger = logging.getLogger(__name__)

# metadata stamp on tasks archived AS PART OF a column trash — restore
# un-archives exactly these tasks, never tasks that were archived on their
# own (individually trashed tasks carry their own recycle-bin entry).
ARCHIVED_BY_COLUMN_KEY = "archived_by_column_trash"


class ColumnSoftDeleteAdapter(SoftDeletePort):
    """Makes a board Column trashable via the recycle bin.

    Soft delete flips ``Column.is_deleted`` and archives the column's live
    tasks (stamping each so restore can tell them apart from independently
    archived tasks). Restore un-flips the column and un-archives exactly the
    stamped tasks, bringing the lane back intact. Hard delete removes the row;
    the Task.column FK is SET_NULL so already-archived tasks survive a purge.
    """

    def soft_delete(self, entity_id: str) -> dict:
        from infrastructure.persistence.project.models import Column, Task

        column = Column.objects.get(pk=entity_id)
        snapshot = {
            "id": str(column.pk),
            "title": column.title,
            "team_id": str(column.team_id),
            "workspace_id": str(column.workspace_id),
            "created_at": str(column.created_at),
        }

        archived_count = 0
        live_tasks = Task.objects.filter(column_id=column.pk).exclude(
            status=Task.ARCHIVED
        )
        for task in live_tasks:
            metadata = dict(task.metadata or {})
            metadata[ARCHIVED_BY_COLUMN_KEY] = str(column.pk)
            metadata[PRE_TRASH_STATUS_KEY] = task.status
            task.metadata = metadata
            task.status = Task.ARCHIVED
            task.save(update_fields=["status", "metadata"])
            archived_count += 1

        column.is_deleted = True
        column.save(update_fields=["is_deleted"])
        snapshot["archived_task_count"] = archived_count
        return snapshot

    def restore(self, entity_id: str) -> None:
        from infrastructure.persistence.project.models import Column, Task

        column = Column.objects.get(pk=entity_id, is_deleted=True)
        column.is_deleted = False
        column.save(update_fields=["is_deleted"])

        # Stamp check happens in Python, not with a JSONField __contains
        # lookup — tests run on SQLite, which doesn't support JSON containment.
        archived = Task.objects.filter(column_id=column.pk, status=Task.ARCHIVED)
        for task in archived:
            metadata = dict(task.metadata or {})
            if metadata.get(ARCHIVED_BY_COLUMN_KEY) != str(column.pk):
                continue
            metadata.pop(ARCHIVED_BY_COLUMN_KEY, None)
            previous_status = metadata.pop(PRE_TRASH_STATUS_KEY, Task.TODO)
            if previous_status == Task.ARCHIVED:
                previous_status = Task.TODO
            task.metadata = metadata
            task.status = previous_status
            task.save(update_fields=["status", "metadata"])

    def hard_delete(self, entity_id: str) -> None:
        from infrastructure.persistence.project.models import Column

        Column.objects.filter(pk=entity_id).delete()

    def entity_type(self) -> str:
        return "column"
