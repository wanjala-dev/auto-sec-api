from __future__ import annotations

import logging

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort

logger = logging.getLogger(__name__)


class ProjectSoftDeleteAdapter(SoftDeletePort):
    """Makes a Project trashable via the recycle bin, like every other entity.

    The Project model carries an ``is_deleted`` flag; the board list queries
    exclude ``is_deleted=True`` so a trashed project drops off the board but is
    fully restorable. Cascade decision: nothing cascades — tasks/columns keep
    their project FK and resolve to the soft-deleted project until a purge, so
    restore brings the whole board back intact (mirrors the recipient adapter,
    whose donations/sponsorships outlive a soft delete).
    """

    def soft_delete(self, entity_id: str) -> dict:
        from infrastructure.persistence.project.models import Project

        project = Project.objects.get(pk=entity_id)
        snapshot = {
            "id": str(project.pk),
            "title": project.title,
            "team_id": str(project.team_id),
            "workspace_id": str(project.workspace_id),
            "created_at": str(project.created_at),
        }

        project.is_deleted = True
        project.save(update_fields=["is_deleted"])
        return snapshot

    def restore(self, entity_id: str) -> None:
        from infrastructure.persistence.project.models import Project

        project = Project.objects.get(pk=entity_id, is_deleted=True)
        project.is_deleted = False
        project.save(update_fields=["is_deleted"])

    def hard_delete(self, entity_id: str) -> None:
        from infrastructure.persistence.project.models import Project

        Project.objects.filter(pk=entity_id).delete()

    def entity_type(self) -> str:
        return "project"
