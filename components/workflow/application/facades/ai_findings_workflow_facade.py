"""Published API for the AI Findings workflow lifecycle.

Phase 4 of the Agents-as-Teammates migration. Other bounded contexts
(workspace bootstrap, identity bootstrap) call this facade to ensure
every workspace has the ``AI Findings Accepted`` workflow + its
``task_moved_column`` binding installed. Idempotent — re-running on
a workspace that already has the workflow is a no-op (one indexed
read, no writes).

The workflow itself is seeded by
``seed_workflow_templates`` (system template ``ai-findings-accepted``);
this facade clones the template into a per-workspace ``Workflow``
instance, publishes it, and installs the ``WorkflowBinding`` that the
dispatcher matches against the ``task_moved_column`` trigger.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TEMPLATE_ID = "ai-findings-accepted"
WORKFLOW_NAME = "AI Findings Accepted"
TRIGGER_TYPE = "task_moved_column"
SOURCE_TYPE = "task"


def ensure_ai_findings_workflow_binding(workspace: Any) -> Any:
    """Ensure the workspace has the AI Findings workflow + binding.

    Steps (each idempotent):

    1. Resolve the ``ai-findings-accepted`` system template. If the
       template isn't seeded yet (fresh DB, pre-migration), log a
       warning and bail — the bootstrap can re-run later. We do not
       seed the template inline because that is the seed command's
       job; doing it here would obscure what wrote which row.
    2. Find-or-create a ``Workflow`` for this workspace cloned from
       the template, status ``published``.
    3. Find-or-create the ``WorkflowBinding`` for
       ``(workflow, source_type='task', trigger_type='task_moved_column')``.

    Returns the binding row when present, ``None`` when the template
    was missing (fresh DB).
    """
    from infrastructure.persistence.workspaces.workflows.models import (
        Workflow,
        WorkflowBinding,
        WorkflowTemplate,
    )

    template = WorkflowTemplate.objects.filter(id=TEMPLATE_ID).first()
    if template is None:
        logger.warning(
            "ai_findings_workflow_template_missing workspace_id=%s template_id=%s",
            workspace.id, TEMPLATE_ID,
        )
        return None

    workflow = (
        Workflow.objects.filter(
            workspace=workspace,
            template=template,
            is_deleted=False,
        )
        .order_by("created_at")
        .first()
    )
    if workflow is None:
        workflow = Workflow.objects.create(
            workspace=workspace,
            name=WORKFLOW_NAME,
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
            workspace.id, workflow.id,
        )
    elif workflow.status != Workflow.Status.PUBLISHED:
        # Adopt an existing draft / paused workflow — we want it live.
        workflow.status = Workflow.Status.PUBLISHED
        workflow.save(update_fields=["status", "updated_at"])

    binding = (
        WorkflowBinding.objects.filter(
            workflow=workflow,
            source_type=SOURCE_TYPE,
            trigger_type=TRIGGER_TYPE,
        )
        .order_by("created_at")
        .first()
    )
    if binding is None:
        binding = WorkflowBinding.objects.create(
            workflow=workflow,
            source_type=SOURCE_TYPE,
            trigger_type=TRIGGER_TYPE,
            is_active=True,
            config={},
        )
        logger.info(
            "ai_findings_workflow_binding_created workspace_id=%s "
            "workflow_id=%s binding_id=%s",
            workspace.id, workflow.id, binding.id,
        )
    elif not binding.is_active:
        binding.is_active = True
        binding.save(update_fields=["is_active", "updated_at"])

    return binding
