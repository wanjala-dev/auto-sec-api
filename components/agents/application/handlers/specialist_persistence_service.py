"""Shared persistence step for specialist handlers and detectors.

Phase 5 of the Agents-as-Teammates migration retired ``AIAction``.
Specialists + detectors now write a single Kanban Task that carries
the detector's narrative on ``Task.description`` and the agent
attribution / detector context on ``Task.metadata``. The Phase 3
helper that wrote a Task plus a shadow ``AIAction`` row no longer
makes sense — there is no second table to shadow.

The helper's job is now:

1. Check idempotency: a finding with the same
   ``(workspace_id, source_type, metadata.idempotency_key)`` already
   exists → no-op return its task_id.
2. Build a ``CreateTaskCommand`` carrying the title + summary +
   structured metadata + ``ai.<action_type>`` source_type.
3. Persist the Task via ``CreateTaskUseCase``.
4. Return the new task_id.

Callers (specialist handlers + ``detector_cycle``) compose the
idempotency_key from whatever fields previously formed the
``AIAction.context`` dedup key — payment_event_id, grant_id +
deadline, period + category_id, etc. The composition is per-caller
because the uniqueness contract is per-caller; the helper just stores
and queries the resulting string.

Lazy imports inside the helper keep the module import-cheap so
``apps.py.ready()`` wiring doesn't drag the ORM into worker bootstrap.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from components.shared_kernel.application.transactional import atomic

logger = logging.getLogger(__name__)


def _derive_severity(impact_score: int) -> str:
    """Map a 0-100 impact_score to the UI's severity tier.

    Threshold tuning lives here so the wire contract stays one
    canonical place. Specialists + detectors don't pass severity in;
    they pass impact_score and the helper computes the tier.
    """
    if impact_score >= 70:
        return "high"
    if impact_score >= 40:
        return "medium"
    return "low"


def persist_finding_as_task(
    *,
    workspace,
    suggested_column,
    ai_user_id: str,
    title: str,
    summary: str,
    source_type: str,
    agent_type: str,
    detector_key: str,
    payload_data: dict[str, Any] | None,
    context: dict[str, Any],
    impact_score: int,
    idempotency_key: str,
    assignee_ids: list[str] | None = None,
) -> str | None:
    """Create the Kanban Task carrying the finding.

    Returns the task_id (string) for logging, or ``None`` if a task
    with the same idempotency_key already exists (caller treats as
    a no-op replay).

    Args:
        workspace: Workspace ORM instance the finding belongs to.
        suggested_column: Column ORM instance on the agent team board.
        ai_user_id: User id that owns the agent team (used as
            ``created_by`` so the team-membership check inside the
            Task port passes).
        title: Card title shown on the Kanban board (truncated at 255).
        summary: Human-readable narrative for ``Task.description``.
        source_type: Provenance label. Convention is
            ``ai.<action_type>`` (e.g. ``ai.donor_payment_succeeded``).
        agent_type: Specialist alias for attribution in the UI.
        detector_key: Detector slug. Stored separately from agent_type
            because the same agent can run multiple detectors.
        payload_data: Structured machine-readable detector output.
        context: Structured detector context.
        impact_score: 0-100 importance, used for sort/visualization.
        idempotency_key: Stable string composed from the caller's
            uniqueness fields. The helper short-circuits if a Task
            with the same ``(workspace, source_type, key)`` exists.
        assignee_ids: Optional user ids to assign to the created task
            (forwarded to ``CreateTaskCommand.assigned_to_ids``). Default
            None → unchanged behaviour for every existing caller. The
            sign-off materializer passes the workspace owner so a pending
            sign-off task lands pre-assigned on the owner's board.

    Returns:
        Created task_id, or ``None`` on idempotent no-op.
    """
    from components.project.application.ports.create_task_port import (
        CreateTaskCommand,
    )
    from components.project.application.providers.project_provider import (
        ProjectProvider,
    )
    from infrastructure.persistence.project.models import Task

    if idempotency_key:
        existing = (
            Task.objects.filter(
                workspace_id=workspace.id,
                source_type=source_type,
                metadata__idempotency_key=idempotency_key,
            )
            .values_list("id", flat=True)
            .first()
        )
        if existing is not None:
            logger.info(
                "specialist_finding_replay_noop workspace_id=%s source_type=%s idempotency_key=%s task_id=%s",
                workspace.id,
                source_type,
                idempotency_key,
                existing,
            )
            return None

    truncated_title = title if len(title) <= 255 else title[:252] + "..."
    score = int(impact_score or 0)
    # ``ai.<action_type>`` → ``<action_type>``. Carries the legacy
    # AIAction.action_type label the frontend widgets still group by.
    action_type = source_type[3:] if source_type.startswith("ai.") else source_type

    # Provenance — every agent-filed card records WHO put it on the board and
    # WHEN, plus a growable audit trail each acting specialist appends to. This
    # is the single creation-time attribution the UI's provenance strip reads;
    # acting agents (triage / optimization) push onto ``provenance.events``.
    created_at = datetime.now(UTC).isoformat()
    confidence = (payload_data or {}).get("confidence") or ""
    provenance = {
        "created_by_kind": "detector",
        "detector": detector_key,
        "assigned_specialist": agent_type,
        "source_type": source_type,
        "created_at": created_at,
        "confidence": confidence,
        "impact_score": score,
        "events": [
            {
                "actor": f"detector:{detector_key}",
                "action": "filed finding on the board",
                "at": created_at,
            }
        ],
    }

    metadata = {
        "agent_type": agent_type,
        "detector": detector_key,
        "action_type": action_type,
        "severity": _derive_severity(score),
        "impact_score": score,
        "ai_headline": truncated_title,
        "ai_narrative": summary or "",
        "idempotency_key": idempotency_key,
        "provenance": provenance,
        # Explicit lifecycle status from birth — the acting specialist flips this
        # to "triaged". Stamped top-level (not just on payload) so the router's
        # not-yet-handled query is unambiguous and never relies on a missing key.
        "triage": {"status": "pending"},
        "payload": payload_data or {},
        "context": context or {},
    }

    with atomic():
        command = CreateTaskCommand(
            title=truncated_title,
            column_id=str(suggested_column.id),
            user_id=ai_user_id,
            workspace_id=str(workspace.id),
            source_type=source_type,
            description=summary or "",
            metadata=metadata,
            assigned_to_ids=assignee_ids or None,
        )
        create_task = ProjectProvider.build_create_task_use_case()
        result = create_task.execute(command=command)

    # A filed finding is a workflow trigger: emit ``finding_raised`` (every
    # finding) plus a severity-scoped trigger so a playbook can bind straight to
    # "critical/high finding". Emitted AFTER the create commits; the dispatcher
    # itself enqueues processing on commit. Best-effort — a workflow-dispatch
    # hiccup must never fail the finding write.
    _emit_finding_triggers(
        workspace_id=str(workspace.id),
        task_id=str(result.task_id),
        severity=metadata["severity"],
        source_type=source_type,
        action_type=action_type,
        detector_key=detector_key,
        headline=truncated_title,
        impact_score=score,
        payload_data=payload_data or {},
    )

    return result.task_id


def _emit_finding_triggers(
    *,
    workspace_id: str,
    task_id: str,
    severity: str,
    source_type: str,
    action_type: str,
    detector_key: str,
    headline: str,
    impact_score: int,
    payload_data: dict[str, Any],
) -> None:
    """Emit the ``finding_*`` workflow triggers for a freshly-filed finding."""
    try:
        from components.workflow.application.providers.workflow_dispatcher_provider import (
            get_workflow_dispatcher_provider,
        )

        emit_workflow_event = get_workflow_dispatcher_provider().emit_workflow_event
        payload = {
            "task_id": task_id,
            "severity": severity,
            "service": str((payload_data or {}).get("service") or "").strip(),
            "action_type": action_type,
            "detector": detector_key,
            "headline": headline,
            "impact_score": impact_score,
            "source_type": source_type,
        }

        def _emit(trigger_type: str) -> None:
            # source_id = the finding's task id so a binding can scope to one
            # finding, and the run targets it.
            emit_workflow_event(
                workspace_id=workspace_id,
                source_type="finding",
                trigger_type=trigger_type,
                source_id=task_id,
                payload=payload,
                idempotency_key=f"{task_id}:{trigger_type}",
            )

        # Every finding fires ``finding_raised``; critical/high additionally fire
        # their severity-scoped trigger (explicit literals so the emit-site
        # completeness check finds each trigger_type).
        _emit(trigger_type="finding_raised")
        if severity == "critical":
            _emit(trigger_type="finding_critical")
        elif severity == "high":
            _emit(trigger_type="finding_high")
    except Exception:
        logger.exception(
            "finding_workflow_emit_failed workspace_id=%s task_id=%s",
            workspace_id,
            task_id,
        )
