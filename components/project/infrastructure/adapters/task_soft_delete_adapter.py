from __future__ import annotations

import logging

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort

logger = logging.getLogger(__name__)

# metadata key remembering the status a task had before it was trashed, so a
# restore puts it back exactly where it was (todo vs done). Task has no
# ``is_deleted`` flag — the project context's soft-delete state is
# ``status=ARCHIVED`` (mirrors ``archive_tasks_for_column`` and the
# assigned-to-me exclusion).
PRE_TRASH_STATUS_KEY = "pre_trash_status"


class TaskSoftDeleteAdapter(SoftDeletePort):
    """Makes a board Task trashable via the recycle bin.

    Soft delete archives the task (``status=ARCHIVED``) and stashes the prior
    status in ``Task.metadata`` so restore is lossless. Board list queries
    exclude archived tasks, so a trashed task drops off every board but stays
    fully restorable. Nothing cascades — comments, time entries, and the
    column FK stay put until a purge hard-deletes the row.
    """

    def soft_delete(self, entity_id: str) -> dict:
        from infrastructure.persistence.project.models import Task

        task = Task.objects.get(pk=entity_id)
        snapshot = {
            "id": str(task.pk),
            "title": task.title,
            "status": task.status,
            "team_id": str(task.team_id),
            "workspace_id": str(task.workspace_id),
            "project_id": str(task.project_id) if task.project_id else None,
            "column_id": str(task.column_id) if task.column_id else None,
            "created_at": str(task.created_at),
        }

        metadata = dict(task.metadata or {})
        metadata[PRE_TRASH_STATUS_KEY] = task.status
        task.metadata = metadata
        task.status = Task.ARCHIVED
        task.save(update_fields=["status", "metadata"])
        return snapshot

    def restore(self, entity_id: str) -> None:
        from infrastructure.persistence.project.models import Task

        task = Task.objects.get(pk=entity_id, status=Task.ARCHIVED)
        metadata = dict(task.metadata or {})
        previous_status = metadata.pop(PRE_TRASH_STATUS_KEY, Task.TODO)
        # Never restore INTO the soft-deleted state itself.
        if previous_status == Task.ARCHIVED:
            previous_status = Task.TODO
        task.metadata = metadata
        task.status = previous_status
        task.save(update_fields=["status", "metadata"])

    def hard_delete(self, entity_id: str) -> None:
        from infrastructure.persistence.project.models import Task

        Task.objects.filter(pk=entity_id).delete()

    def entity_type(self) -> str:
        return "task"
