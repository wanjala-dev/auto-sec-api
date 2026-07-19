"""Celery tasks for workflow execution.

The engine is an outbox -> Celery chain that walks a workflow graph one node at
a time, persisting per-node state under a row lock for idempotency.

Autonomy (the GTM keystone): ``condition`` and ``wait_until`` nodes branch
*server-side* with no human in the loop —
- ``condition`` evaluates a predicate (domain ``evaluate_condition``) against the
  run context and takes the Yes/No edge immediately.
- ``wait_until`` waits for a domain event (e.g. the contact makes a transaction)
  up to a timeout, then branches Yes (event arrived, resolved by the dispatcher)
  / No (timed out, resolved by the re-enqueued step).

The legacy ``decision`` / ``data_request`` nodes still PAUSE for a manual
``complete_step`` / ``input_step`` API call — reserve those for genuine
human-in-the-loop steps, not for automation logic.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from celery import shared_task
from django.db import router, transaction
from django.utils import timezone

from components.workflow.domain.services.condition_evaluator import (
    evaluate_condition,
    evaluate_switch,
)
from components.workflow.domain.value_objects.workflow_graph import WorkflowGraph
from components.workflow.infrastructure.adapters.dispatcher import dispatch_event
from components.workflow.infrastructure.adapters.node_actions import (
    execute_node_action,
    prepare_email_signoff,
)
from infrastructure.persistence.workspaces.workflows.models import (
    WorkflowRun,
    WorkflowStepEvent,
    WorkflowStepState,
)

logger = logging.getLogger(__name__)

ACTION_NODE_TYPES = {
    "message",
    "task",
    "ai",
    "assign",
    "add_tag",
    "remove_tag",
    "update_field",
    "webhook",
    "publish_event",
}
# Nodes that pause the run for an external API call (human in the loop).
HUMAN_PAUSE_NODE_TYPES = {"decision", "data_request"}


# ---------------------------------------------------------------------------
# Context + state helpers
# ---------------------------------------------------------------------------
def _build_run_context(run: WorkflowRun) -> dict[str, Any]:
    """Assemble the context a ``condition`` evaluates against.

    Merges the trigger payload with target identity and prior step outputs so a
    predicate can reference ``amount``, ``contact.tags``, ``trigger.campaign_id``
    or ``steps.<node_id>.satisfied``.
    """
    payload = dict(run.trigger_payload or {})
    context: dict[str, Any] = dict(payload)
    context.setdefault("target_id", run.target_id)
    context.setdefault("target_type", run.target_type)
    context["trigger_type"] = run.trigger_type
    context["trigger"] = payload

    steps: dict[str, Any] = {}
    for state in WorkflowStepState.objects.filter(run=run).only("node_id", "output"):
        if state.output:
            steps[state.node_id] = state.output
    context["steps"] = steps
    return context


def _log_step_event(run: WorkflowRun, node_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
    WorkflowStepEvent.objects.create(run=run, node_id=node_id, event_type=event_type, payload=payload or {})


def _mark_state_completed(state: WorkflowStepState, output: dict[str, Any] | None = None) -> None:
    state.status = "completed"
    state.completed_at = timezone.now()
    if output:
        state.output = output
        state.save(update_fields=["status", "completed_at", "output", "updated_at"])
    else:
        state.save(update_fields=["status", "completed_at", "updated_at"])


def _notify_run_finished(run: WorkflowRun, status: str) -> None:
    """Tell the workflow's owner (in-app) that a run finished or failed.

    Best-effort: the run outcome is already decided, so a notification failure
    must NOT fail the run — log and continue (per logging rule §7's documented
    log-and-continue exception). Mirrors the in-app Notification pattern used by
    the message executor.
    """
    workflow = getattr(run, "workflow", None)
    owner_id = getattr(workflow, "created_by_id", None)
    if not workflow or not owner_id:
        return
    name = getattr(workflow, "name", None) or "Workflow"
    verb = f"Workflow “{name}” completed a run" if status == "completed" else f"Workflow “{name}” run failed"
    try:
        from django.contrib.auth import get_user_model

        from components.notifications.infrastructure.adapters.notification_service import (
            NotificationDispatcher,
        )
        from infrastructure.persistence.notifications.models import Notification
        from infrastructure.persistence.workspaces.models import Workspace

        owner = get_user_model().objects.filter(pk=owner_id).first()
        if owner is None:
            return
        workspace = Workspace.objects.filter(id=workflow.workspace_id).first()

        # System-generated; there is no acting user in an automated run, so
        # the owner stands in as actor — allow_self_notify keeps the funnel
        # from dropping it.
        NotificationDispatcher().dispatch(
            actor=owner,
            workspace=workspace,
            verb=verb[:255],
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[owner],
            metadata={"kind": "workflow.run_finished", "run_id": str(run.id), "status": status},
            allow_self_notify=True,
        )
        logger.info(
            "workflow_run_notified run_id=%s status=%s owner_id=%s",
            run.id,
            status,
            owner_id,
        )
    except Exception:
        logger.exception("workflow_run_notify_failed run_id=%s status=%s", run.id, status)


def _fail_run(run: WorkflowRun, state: WorkflowStepState, node_id: str, exc: Exception) -> None:
    _log_step_event(run, node_id, "failed", {"error": str(exc)})
    state.status = "failed"
    state.last_error = str(exc)[:2000]
    state.completed_at = timezone.now()
    state.save(update_fields=["status", "last_error", "completed_at", "updated_at"])
    run.status = WorkflowRun.Status.FAILED
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "completed_at", "updated_at"])
    _notify_run_finished(run, "failed")


def _advance_to(run: WorkflowRun, next_node_id: str | None) -> None:
    if not next_node_id:
        workflow_run_complete.delay(str(run.id))
        return
    run.current_node_id = next_node_id
    run.status = WorkflowRun.Status.RUNNING
    run.paused_at = None
    run.save(update_fields=["current_node_id", "status", "paused_at", "updated_at"])
    workflow_run_step.delay(str(run.id), next_node_id)


def _branch_and_advance(
    run: WorkflowRun,
    node_id: str,
    graph: WorkflowGraph,
    outcome: Any,
    state: WorkflowStepState,
) -> None:
    """Complete a branching node, log the outcome, and advance the chosen edge."""
    next_node_id = graph.branch_target(node_id, outcome)
    _mark_state_completed(state)
    _log_step_event(run, node_id, "branched", {"outcome": outcome, "to": next_node_id})
    _advance_to(run, next_node_id)


def _park_for_signoff(
    run: WorkflowRun,
    node_id: str,
    state: WorkflowStepState,
    signoff: dict[str, Any],
) -> None:
    """Park an AI-derived email step pending a human sign-off.

    The parked step IS the pending sign-off artifact (no new model): its
    ``output["signoff"]`` blob holds the content + grounding + review_state the
    ``WorkflowEmailSignOffAdapter`` reads, and its ``waiting_input`` status maps
    to ``ReviewState.PENDING``. We reuse the decision-node pause exactly — step
    ``waiting_input`` + run ``PAUSED`` — so the run WAITS instead of sending or
    erroring. The email is NOT sent. The approve->resume->send UX is Phase 6.
    """
    state.status = "waiting_input"
    state.output = {"signoff": signoff}
    state.save(update_fields=["status", "output", "updated_at"])
    if run.status != WorkflowRun.Status.PAUSED:
        run.status = WorkflowRun.Status.PAUSED
        run.paused_at = timezone.now()
        run.save(update_fields=["status", "paused_at", "updated_at"])
    _log_step_event(
        run,
        node_id,
        "entered",
        {"parked_for_signoff": True, "artifact_type": signoff.get("artifact_type")},
    )
    logger.info(
        "workflow_email parked for sign-off run_id=%s step_id=%s node_id=%s artifact_type=%s",
        run.id,
        state.id,
        node_id,
        signoff.get("artifact_type"),
    )


# ---------------------------------------------------------------------------
# Outbox -> dispatch
# ---------------------------------------------------------------------------
@shared_task(
    name="workflow_event_process",
    bind=True,
    max_retries=3,
    soft_time_limit=240,
    time_limit=300,
)
def workflow_event_process(self, event_id: str) -> int:
    """Process workflow outbox events and enqueue matching runs."""
    from infrastructure.persistence.workspaces.workflows.models import WorkflowEvent

    event = WorkflowEvent.objects.select_related("workspace").get(id=event_id)
    if event.status == "processed":
        return 0

    logger.info(
        "workflow_event_process started event_id=%s trigger=%s task_id=%s",
        event_id,
        event.trigger_type,
        self.request.id,
    )
    try:
        event.status = "processing"
        event.save(update_fields=["status"])
        count = dispatch_event(event)
        logger.info("workflow_event_process completed event_id=%s runs=%s", event_id, count)
        return count
    except Exception as exc:
        event.status = "failed"
        event.last_error = str(exc)[:2000]
        event.save(update_fields=["status", "last_error"])
        logger.exception("workflow_event_process failed event_id=%s", event_id)
        raise


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------
@shared_task(
    name="workflow_run_start",
    bind=True,
    max_retries=3,
    soft_time_limit=240,
    time_limit=300,
)
def workflow_run_start(self, run_id: str) -> None:
    """Initialize a workflow run and enqueue its first node."""
    run = WorkflowRun.objects.select_related("workflow").get(id=run_id)
    if run.status not in {WorkflowRun.Status.QUEUED, WorkflowRun.Status.PAUSED}:
        return

    graph = WorkflowGraph(run.workflow.graph)
    start_node_id = graph.start_node_id()
    if not start_node_id:
        logger.warning("workflow_run_start no_single_start run_id=%s", run_id)
        run.status = WorkflowRun.Status.FAILED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])
        return

    run.status = WorkflowRun.Status.RUNNING
    run.started_at = run.started_at or timezone.now()
    run.current_node_id = start_node_id
    run.save(update_fields=["status", "started_at", "current_node_id"])

    _log_step_event(run, start_node_id, "entered")
    workflow_run_step.delay(str(run.id), start_node_id)


@shared_task(
    name="workflow_run_step",
    bind=True,
    max_retries=3,
    soft_time_limit=240,
    time_limit=300,
)
def workflow_run_step(self, run_id: str, node_id: str) -> None:
    """Execute a single node in a workflow."""
    run = WorkflowRun.objects.select_related("workflow").get(id=run_id)
    if run.status in {
        WorkflowRun.Status.CANCELED,
        WorkflowRun.Status.FAILED,
        WorkflowRun.Status.COMPLETED,
        WorkflowRun.Status.PAUSED,
    }:
        return

    graph = WorkflowGraph(run.workflow.graph)
    node = graph.node(node_id)
    if not node:
        logger.warning("workflow_run_step unknown_node run_id=%s node_id=%s", run_id, node_id)
        run.status = WorkflowRun.Status.FAILED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])
        return

    node_type = node.get("type")
    config = node.get("config") or {}

    # Lock + claim the per-node state (idempotency anchor). Route the atomic to
    # the tenant DB the model lives on (a bare atomic() only covers 'default').
    db_alias = router.db_for_write(WorkflowStepState)
    entered = False
    with transaction.atomic(using=db_alias):
        state, _ = (
            WorkflowStepState.objects.using(db_alias)
            .select_for_update()
            .get_or_create(run=run, node_id=node_id, defaults={"status": "pending"})
        )
        if state.status == "completed":
            return
        if state.status == "pending":
            state.status = "running"
            state.attempts += 1
            state.started_at = state.started_at or timezone.now()
            state.save(update_fields=["status", "attempts", "started_at", "updated_at"])
            entered = True

    if entered and node_type != "start":
        _log_step_event(run, node_id, "entered")

    # -- terminal -----------------------------------------------------------
    if node_type == "end":
        _mark_state_completed(state)
        _log_step_event(run, node_id, "completed")
        workflow_run_complete.delay(str(run.id))
        return

    # -- delay --------------------------------------------------------------
    if node_type == "wait":
        if state.status != "waiting":
            state.status = "waiting"
            state.save(update_fields=["status", "updated_at"])
            workflow_run_step.apply_async((run_id, node_id), countdown=_resolve_countdown(config))
            return
        _mark_state_completed(state)
        _advance_to(run, graph.default_target(node_id))
        return

    # -- autonomous timed wait (event-or-timeout) ---------------------------
    if node_type == "wait_until":
        _handle_wait_until(run, node_id, config, graph, state, db_alias)
        return

    # -- autonomous branch --------------------------------------------------
    if node_type == "condition":
        context = _build_run_context(run)
        predicate = config.get("predicate")
        if predicate is None and ("conditions" in config or "field" in config):
            predicate = config  # allow conditions inlined on config
        try:
            outcome = evaluate_condition(predicate, context)
        except Exception as exc:
            logger.exception("workflow_condition_failed run_id=%s node_id=%s", run_id, node_id)
            _fail_run(run, state, node_id, exc)
            return
        _branch_and_advance(run, node_id, graph, outcome, state)
        return

    # -- autonomous multi-way branch ---------------------------------------
    if node_type == "switch":
        context = _build_run_context(run)
        try:
            outcome = evaluate_switch(config, context)
        except Exception as exc:
            logger.exception("workflow_switch_failed run_id=%s node_id=%s", run_id, node_id)
            _fail_run(run, state, node_id, exc)
            return
        # outcome is the matching case label (a string) or None -> branch_target
        # resolves None to the first edge as a safety fallback.
        _branch_and_advance(run, node_id, graph, outcome, state)
        return

    # -- human-in-the-loop pause -------------------------------------------
    if node_type in HUMAN_PAUSE_NODE_TYPES:
        if state.status != "waiting_input":
            state.status = "waiting_input"
            state.save(update_fields=["status", "updated_at"])
            run.status = WorkflowRun.Status.PAUSED
            run.paused_at = timezone.now()
            run.save(update_fields=["status", "paused_at"])
        return

    # -- action nodes (fail loudly) ----------------------------------------
    if node_type in ACTION_NODE_TYPES:
        # Sign-off gate (Phase 3): AI-derived email content can NEVER auto-send
        # unreviewed. A message node whose email body is AI-generated parks here
        # — pending a human sign-off — reusing the SAME pause mechanism the
        # ``decision`` node uses (step ``waiting_input`` + run ``PAUSED``).
        # Deterministic template emails return None and send exactly as before.
        if node_type == "message":
            signoff = prepare_email_signoff(run, node, config, graph)
            if signoff is not None:
                _park_for_signoff(run, node_id, state, signoff)
                return
        try:
            output = execute_node_action(run, node, config)
            if isinstance(output, dict) and output.get("status") == "failed":
                # Defensive backstop: an executor should raise, but if any path
                # still returns a failed dict, do not record it as completed.
                raise RuntimeError(output.get("error") or output.get("reason") or "action failed")
        except Exception as exc:
            logger.exception(
                "workflow_action_failed node_type=%s run_id=%s node_id=%s",
                node_type,
                run_id,
                node_id,
            )
            _fail_run(run, state, node_id, exc)
            return
        _mark_state_completed(state, output if output else None)
        _log_step_event(run, node_id, "completed", output or None)
        _advance_to(run, graph.default_target(node_id))
        return

    # -- start / unknown passthrough ---------------------------------------
    _mark_state_completed(state)
    _log_step_event(run, node_id, "completed")
    _advance_to(run, graph.default_target(node_id))


def _resolve_countdown(config: dict[str, Any]) -> int:
    delay_until = config.get("delay_until") or config.get("timeout_until")
    if delay_until:
        try:
            eta = datetime.fromisoformat(str(delay_until).replace("Z", "+00:00"))
            return max(int((eta - timezone.now()).total_seconds()), 0)
        except (ValueError, TypeError):
            return 0
    return int(config.get("delay_seconds") or config.get("timeout_seconds") or 0)


def _handle_wait_until(
    run: WorkflowRun,
    node_id: str,
    config: dict[str, Any],
    graph: WorkflowGraph,
    state: WorkflowStepState,
    db_alias: str,
) -> None:
    """First entry: arm the wait + schedule the timeout. Re-entry: time out -> No.

    Early resolution (event arrived) is handled by ``workflow_wait_until_resolve``,
    enqueued from the dispatcher. Row locking makes the two paths mutually
    exclusive — whichever claims the ``waiting`` state first wins.
    """
    awaited_event = config.get("event")

    if state.status == "waiting":
        # Re-entry = the timeout fired. Claim the state; if the resolve task
        # already took it, bail.
        with transaction.atomic(using=db_alias):
            locked = WorkflowStepState.objects.using(db_alias).select_for_update().get(pk=state.pk)
            if locked.status != "waiting":
                return
            locked.status = "running"
            locked.save(update_fields=["status", "updated_at"])
            state = locked
        _branch_and_advance(run, node_id, graph, False, state)  # timed out -> No
        return

    # First entry: arm the wait and schedule the timeout re-entry.
    deadline = timezone.now()
    countdown = _resolve_countdown(config)
    state.status = "waiting"
    state.output = {
        "awaiting_event": awaited_event,
        "armed_at": deadline.isoformat(),
    }
    state.save(update_fields=["status", "output", "updated_at"])
    workflow_run_step.apply_async((str(run.id), node_id), countdown=countdown)


@shared_task(
    name="workflow_wait_until_resolve",
    bind=True,
    max_retries=3,
    soft_time_limit=120,
    time_limit=180,
)
def workflow_wait_until_resolve(self, run_id: str, node_id: str) -> None:
    """Resolve a ``wait_until`` node early because its awaited event arrived."""
    run = WorkflowRun.objects.select_related("workflow").get(id=run_id)
    if run.status != WorkflowRun.Status.RUNNING:
        return
    graph = WorkflowGraph(run.workflow.graph)
    if graph.node_type(node_id) != "wait_until":
        return

    db_alias = router.db_for_write(WorkflowStepState)
    with transaction.atomic(using=db_alias):
        state = WorkflowStepState.objects.using(db_alias).select_for_update().filter(run=run, node_id=node_id).first()
        if not state or state.status != "waiting":
            return  # timeout already claimed it, or not armed
        state.status = "running"
        state.save(update_fields=["status", "updated_at"])

    _branch_and_advance(run, node_id, graph, True, state)  # event happened -> Yes


@shared_task(
    name="workflow_run_branch",
    bind=True,
    max_retries=3,
    soft_time_limit=240,
    time_limit=300,
)
def workflow_run_branch(self, run_id: str, node_id: str, output: dict[str, Any] | None = None) -> None:
    """Select the next edge after a LEGACY ``decision`` node is completed by the API."""
    run = WorkflowRun.objects.select_related("workflow").get(id=run_id)
    graph = WorkflowGraph(run.workflow.graph)
    outcome = (output or {}).get("decision")

    next_node_id = graph.branch_target(node_id, outcome)
    _log_step_event(run, node_id, "branched", {"outcome": outcome, "to": next_node_id})
    _advance_to(run, next_node_id)


@shared_task(
    name="workflow_run_complete",
    bind=True,
    max_retries=3,
    soft_time_limit=240,
    time_limit=300,
)
def workflow_run_complete(self, run_id: str) -> None:
    """Finalize a workflow run."""
    run = WorkflowRun.objects.get(id=run_id)
    if run.status in {WorkflowRun.Status.COMPLETED, WorkflowRun.Status.CANCELED}:
        return
    run.status = WorkflowRun.Status.COMPLETED
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "completed_at", "updated_at"])
    _notify_run_finished(run, "completed")
