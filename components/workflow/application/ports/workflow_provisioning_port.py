"""Port for provisioning the per-workspace AI Findings workflow + binding.

The ``ai_findings_workflow_facade`` orchestrates the (idempotent) install of
the ``AI Findings Accepted`` workflow and its ``task_moved_column`` binding for
a workspace. That choreography is application-layer policy; the ORM reads/writes
it needs live behind THIS port so the facade never imports
``infrastructure.persistence.workspaces.workflows`` directly.

The adapter (``infrastructure/repositories/workflow_provisioning_repository.py``)
owns the Django ORM and returns the frozen ``WorkflowBindingDTO`` across the
boundary — never an ORM instance.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class WorkflowBindingDTO:
    """Immutable view of the provisioned ``WorkflowBinding`` row."""

    id: UUID
    workflow_id: UUID
    source_type: str
    trigger_type: str
    is_active: bool


class WorkflowProvisioningPort(ABC):
    """Provision the AI Findings workflow + binding for a workspace."""

    @abstractmethod
    def ensure_ai_findings_binding(
        self,
        *,
        workspace_id: UUID,
        template_id: str,
        workflow_name: str,
        source_type: str,
        trigger_type: str,
    ) -> WorkflowBindingDTO | None:
        """Find-or-create the workflow + binding; return the binding DTO.

        Returns ``None`` when the system template ``template_id`` isn't seeded
        yet (fresh DB) so the caller can retry later. Idempotent — re-running on
        an already-provisioned workspace is a no-op that returns the existing
        binding.
        """
        ...
