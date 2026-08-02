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

The workflow ORM lives behind ``WorkflowProvisioningPort`` (wired via
``get_workflow_provisioning_provider``); the facade owns the policy
(which template, which trigger) and delegates the persistence.
"""

from __future__ import annotations

from typing import Any

from components.workflow.application.ports.workflow_provisioning_port import (
    WorkflowBindingDTO,
)
from components.workflow.application.providers.workflow_provisioning_provider import (
    get_workflow_provisioning_provider,
)

TEMPLATE_ID = "ai-findings-accepted"
WORKFLOW_NAME = "AI Findings Accepted"
TRIGGER_TYPE = "task_moved_column"
SOURCE_TYPE = "task"


def ensure_ai_findings_workflow_binding(workspace: Any) -> WorkflowBindingDTO | None:
    """Ensure the workspace has the AI Findings workflow + binding.

    Steps (each idempotent, owned by ``WorkflowProvisioningPort``):

    1. Resolve the ``ai-findings-accepted`` system template. If the
       template isn't seeded yet (fresh DB, pre-migration), the port
       logs a warning and returns ``None`` — the bootstrap can re-run
       later. We do not seed the template inline because that is the
       seed command's job.
    2. Find-or-create a ``Workflow`` for this workspace cloned from
       the template, status ``published``.
    3. Find-or-create the ``WorkflowBinding`` for
       ``(workflow, source_type='task', trigger_type='task_moved_column')``.

    Returns the binding DTO when present, ``None`` when the template
    was missing (fresh DB).
    """
    provider = get_workflow_provisioning_provider()
    return provider.port().ensure_ai_findings_binding(
        workspace_id=workspace.id,
        template_id=TEMPLATE_ID,
        workflow_name=WORKFLOW_NAME,
        source_type=SOURCE_TYPE,
        trigger_type=TRIGGER_TYPE,
    )
