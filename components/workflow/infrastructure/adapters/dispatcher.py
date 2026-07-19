"""Workflow event dispatcher for feature integrations."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from infrastructure.persistence.workspaces.workflows.models import (
    WorkflowBinding,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStepState,
)

logger = logging.getLogger(__name__)


def emit_workflow_event(
    *,
    workspace_id: str,
    source_type: str,
    trigger_type: str,
    payload: Optional[Dict[str, Any]] = None,
    source_id: Optional[str] = None,
    idempotency_key: str = "",
) -> WorkflowEvent:
    """Persist a workflow event and enqueue processing after commit."""

    event = WorkflowEvent.objects.create(
        workspace_id=workspace_id,
        source_type=source_type,
        source_id=source_id,
        trigger_type=trigger_type,
        payload=payload or {},
        idempotency_key=idempotency_key or "",
    )

    from components.workflow.infrastructure.tasks.workflow_tasks import workflow_event_process

    transaction.on_commit(lambda: workflow_event_process.delay(str(event.id)))
    return event


def dispatch_event(event: WorkflowEvent) -> int:
    """Start workflow runs for bindings that match the event.

    Also wakes any ``wait_until`` steps in already-running runs that were
    waiting for *this* event for *this* target (early resolution -> Yes branch).
    """

    target_type = event.payload.get("target_type", "contact")
    target_id = event.payload.get("target_id") or event.payload.get("contact_id")

    bindings = WorkflowBinding.objects.select_related("workflow").filter(
        workflow__workspace_id=event.workspace_id,
        source_type=event.source_type,
        trigger_type=event.trigger_type,
        is_active=True,
    )

    # A workspace-wide binding (the default that publishing a workflow creates)
    # has source_id NULL — it should fire for ANY source. SQL ``IN`` never
    # matches NULL rows (``x IN (NULL)`` is never true), so we MUST OR in an
    # explicit ``isnull`` term; ``source_id__in=[..., None]`` silently drops the
    # NULL bindings and the workflow never runs. A binding WITH a source_id is
    # scoped to that one source.
    unscoped = Q(source_id__isnull=True) | Q(source_id="")
    if event.source_id:
        bindings = bindings.filter(Q(source_id=event.source_id) | unscoped)
    else:
        bindings = bindings.filter(unscoped)

    from components.workflow.infrastructure.tasks.workflow_tasks import workflow_run_start

    run_count = 0
    for binding in bindings:
        if not target_id:
            logger.warning(
                "workflow_event_dropped no_target trigger=%s workflow_id=%s event_id=%s",
                event.trigger_type, binding.workflow_id, event.id,
            )
            continue
        run = WorkflowRun.objects.create(
            workflow=binding.workflow,
            workflow_version=binding.workflow.version,
            status=WorkflowRun.Status.QUEUED,
            trigger_type=event.trigger_type,
            trigger_payload=event.payload,
            target_type=target_type,
            target_id=str(target_id),
        )
        workflow_run_start.delay(str(run.id))
        run_count += 1

    if target_id:
        _resolve_wait_until_steps(event, target_id)

    event.status = "processed"
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "processed_at"])
    return run_count


def _resolve_wait_until_steps(event: WorkflowEvent, target_id: Any) -> None:
    """Wake ``wait_until`` steps whose awaited event just arrived for this target."""
    from components.workflow.infrastructure.tasks.workflow_tasks import (
        workflow_wait_until_resolve,
    )

    waiting = (
        WorkflowStepState.objects.filter(
            status="waiting",
            run__workflow__workspace_id=event.workspace_id,
            run__target_id=str(target_id),
            run__status=WorkflowRun.Status.RUNNING,
        )
        .only("id", "node_id", "output", "run_id")
        .select_related("run")
    )
    for state in waiting:
        awaited = (state.output or {}).get("awaiting_event")
        if awaited and str(awaited) == str(event.trigger_type):
            workflow_wait_until_resolve.delay(str(state.run_id), state.node_id)
