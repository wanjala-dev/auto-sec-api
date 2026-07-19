from __future__ import annotations

import logging

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort

logger = logging.getLogger(__name__)


class WorkflowSoftDeleteAdapter(SoftDeletePort):
    """Soft-delete / restore / purge a workflow via the shared recycle bin.

    A workflow uses ``is_deleted`` for soft delete. ``Delete`` (recycle bin)
    sets it true and records a snapshot so the bin can show the workflow's name
    and Restore can bring it back. This is distinct from ``Archive``, which only
    flips ``status`` to archived and keeps the workflow listable.

    Cascade decision: nothing cascades. WorkflowRun / WorkflowStepEvent rows are
    historical execution records and outlive the workflow definition; bindings
    stay so a restore re-activates the same triggers. A purge (hard_delete)
    cascades at the DB level via the FKs.
    """

    def soft_delete(self, entity_id: str) -> dict:
        from infrastructure.persistence.workspaces.workflows.models import Workflow
        from django.utils import timezone

        workflow = Workflow.objects.get(id=entity_id)
        snapshot = {
            "id": str(workflow.id),
            "name": workflow.name,
            "status": workflow.status,
            "workspace_id": str(workflow.workspace_id),
            "created_at": str(workflow.created_at),
        }

        workflow.is_deleted = True
        workflow.updated_at = timezone.now()
        workflow.save(update_fields=["is_deleted", "updated_at"])
        return snapshot

    def restore(self, entity_id: str) -> None:
        from infrastructure.persistence.workspaces.workflows.models import Workflow
        from django.utils import timezone

        workflow = Workflow.objects.get(id=entity_id, is_deleted=True)
        workflow.is_deleted = False
        workflow.updated_at = timezone.now()
        workflow.save(update_fields=["is_deleted", "updated_at"])

    def hard_delete(self, entity_id: str) -> None:
        from infrastructure.persistence.workspaces.workflows.models import Workflow

        Workflow.objects.filter(id=entity_id).delete()

    def entity_type(self) -> str:
        return "workflow"
