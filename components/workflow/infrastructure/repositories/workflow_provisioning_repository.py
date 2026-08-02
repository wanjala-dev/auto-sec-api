"""ORM adapter for the AI Findings workflow-provisioning port.

Owns the ``Workflow`` / ``WorkflowBinding`` / ``WorkflowTemplate`` reads +
writes the facade used to do inline. Each step is idempotent; see the port
docstring for the contract.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.workflow.application.ports.workflow_provisioning_port import (
    WorkflowBindingDTO,
    WorkflowProvisioningPort,
)

logger = logging.getLogger(__name__)


class WorkflowProvisioningRepository(WorkflowProvisioningPort):
    def ensure_ai_findings_binding(
        self,
        *,
        workspace_id: UUID,
        template_id: str,
        workflow_name: str,
        source_type: str,
        trigger_type: str,
    ) -> WorkflowBindingDTO | None:
        from infrastructure.persistence.workspaces.workflows.models import (
            Workflow,
            WorkflowBinding,
            WorkflowTemplate,
        )

        template = WorkflowTemplate.objects.filter(id=template_id).first()
        if template is None:
            logger.warning(
                "ai_findings_workflow_template_missing workspace_id=%s template_id=%s",
                workspace_id,
                template_id,
            )
            return None

        workflow = (
            Workflow.objects.filter(
                workspace_id=workspace_id,
                template=template,
                is_deleted=False,
            )
            .order_by("created_at")
            .first()
        )
        if workflow is None:
            workflow = Workflow.objects.create(
                workspace_id=workspace_id,
                name=workflow_name,
                description=template.description,
                goal="agents",
                template=template,
                is_custom=False,
                status=Workflow.Status.PUBLISHED,
                version=1,
                graph=template.default_graph,
                created_by=None,
            )
            logger.info(
                "ai_findings_workflow_provisioned workspace_id=%s workflow_id=%s",
                workspace_id,
                workflow.id,
            )
        elif workflow.status != Workflow.Status.PUBLISHED:
            # Adopt an existing draft / paused workflow — we want it live.
            workflow.status = Workflow.Status.PUBLISHED
            workflow.save(update_fields=["status", "updated_at"])

        binding = (
            WorkflowBinding.objects.filter(
                workflow=workflow,
                source_type=source_type,
                trigger_type=trigger_type,
            )
            .order_by("created_at")
            .first()
        )
        if binding is None:
            binding = WorkflowBinding.objects.create(
                workflow=workflow,
                source_type=source_type,
                trigger_type=trigger_type,
                is_active=True,
                config={},
            )
            logger.info(
                "ai_findings_workflow_binding_created workspace_id=%s workflow_id=%s binding_id=%s",
                workspace_id,
                workflow.id,
                binding.id,
            )
        elif not binding.is_active:
            binding.is_active = True
            binding.save(update_fields=["is_active", "updated_at"])

        return WorkflowBindingDTO(
            id=binding.id,
            workflow_id=workflow.id,
            source_type=binding.source_type,
            trigger_type=binding.trigger_type,
            is_active=binding.is_active,
        )
