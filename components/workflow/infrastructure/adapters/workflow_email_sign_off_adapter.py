"""Sign-off adapter for AI-derived workflow emails.

Implements the sign-off kernel's :class:`SignOffPort` against the **parked
``WorkflowStepState`` row** of an ``ai``-content message node — there is NO new
model. When the engine detects an AI-generated email it parks the step
(``waiting_input`` + run ``PAUSED``) and stashes a ``signoff`` blob on
``WorkflowStepState.output``; that parked step *is* the pending artifact. This
adapter reads/writes that row so the kernel can treat a workflow email exactly
like any other reviewable artifact (financial report, newsletter, ...) — one
queue, one state machine, one set of receipts.

State persistence (the parked step IS the state):

- The canonical ``ReviewState`` lives in ``output["signoff"]["review_state"]``
  for a faithful 4-state round-trip; the step's own ``status`` is kept in sync
  (``waiting_input`` ↔ PENDING/CHANGES_REQUESTED, ``completed`` ↔ APPROVED,
  ``failed`` ↔ REJECTED) so the engine's pause + a future resume see a
  consistent step.

Receipts are built by re-running the deterministic :class:`FaithfulnessVerifier`
(a cross-context *domain* service — allowed) over the AI email body against the
grounding corpus captured at park time (trigger payload + step outputs). We do
not do ledger-contradiction detection here, so every unverifiable figure
surfaces as *unverifiable* (amber), never *contradicted* (red) — the honest
signal: "we couldn't confirm this number against the source we have".
"""

from __future__ import annotations

import logging

from django.utils import timezone

from components.agents.domain.services.faithfulness_verifier import FaithfulnessVerifier
from components.sign_off.application.ports.sign_off_port import SignOffPort
from components.sign_off.application.services.sign_off_item_builder import build_sign_off_item
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.reviewer_receipts import (
    ClaimProvenance,
    FigureCheck,
    ReviewerReceipts,
)
from components.sign_off.domain.value_objects.sign_off_item import SignOffItem
from components.sign_off.domain.value_objects.sign_off_target import Audience, SignOffTarget
from components.shared_kernel.domain.errors import NotFoundError

logger = logging.getLogger(__name__)

_ARTIFACT_TYPE = "workflow_email"

# Map the workflow step status <-> the kernel review state. The parked step's
# ``waiting_input`` is the pending artifact; an approval completes the step, a
# rejection fails it. CHANGES_REQUESTED keeps the step parked (still awaiting a
# human), same as PENDING from the engine's pause perspective.
_STATUS_TO_STATE = {
    "waiting_input": ReviewState.PENDING,
    "completed": ReviewState.APPROVED,
    "failed": ReviewState.REJECTED,
}
_STATE_TO_STATUS = {
    ReviewState.PENDING: "waiting_input",
    ReviewState.CHANGES_REQUESTED: "waiting_input",
    ReviewState.APPROVED: "completed",
    ReviewState.REJECTED: "failed",
}
# States that stamp ``completed_at`` on the step (terminal-ish decisions).
_DECISION_STATES = frozenset({ReviewState.APPROVED, ReviewState.REJECTED})


class WorkflowEmailSignOffAdapter(SignOffPort):
    """Maps the sign-off kernel onto a parked workflow-email ``WorkflowStepState``."""

    def artifact_type(self) -> str:
        return _ARTIFACT_TYPE

    def get_state(self, artifact_id: str) -> ReviewState:
        step = self._get_step(artifact_id)
        raw = self._signoff(step).get("review_state")
        if raw:
            return ReviewState(raw)
        # Fall back to the step status if the blob predates review_state.
        return _STATUS_TO_STATE.get(step.status, ReviewState.PENDING)

    def set_state(self, artifact_id: str, state: ReviewState) -> None:
        step = self._get_step(artifact_id)
        output = dict(step.output or {})
        signoff = dict(output.get("signoff") or {})
        signoff["review_state"] = state.value
        output["signoff"] = signoff
        step.output = output
        step.status = _STATE_TO_STATUS[state]
        fields = ["output", "status", "updated_at"]
        if state in _DECISION_STATES:
            step.completed_at = timezone.now()
            fields.append("completed_at")
        step.save(update_fields=fields)

    def build_receipts(self, artifact_id: str) -> ReviewerReceipts:
        step = self._get_step(artifact_id)
        signoff = self._signoff(step)
        result = FaithfulnessVerifier().verify(
            generated_html=signoff.get("content") or "",
            grounding_texts=list(signoff.get("grounding") or []),
        )
        figure_checks = tuple(
            # No source value found -> unverifiable (amber), not contradicted.
            FigureCheck(claim_text=token, stated_value=token, source_value=None, verified=False)
            for token in result.unsupported_numbers
        )
        claim_provenance = tuple(
            ClaimProvenance(claim_text=name, source_record_ref=None, grounded=False)
            for name in result.unsupported_names
        )
        return ReviewerReceipts(
            figure_checks=figure_checks,
            claim_provenance=claim_provenance,
        )

    def target(self, artifact_id: str) -> SignOffTarget:
        step = self._get_step(artifact_id)
        audience_raw = self._signoff(step).get("audience")
        audience = Audience.EXTERNAL if audience_raw == "external" else Audience.INTERNAL_TEAM
        return SignOffTarget(audience=audience)

    def workspace_id(self, artifact_id: str) -> str | None:
        from infrastructure.persistence.workspaces.workflows.models import WorkflowStepState

        row = (
            WorkflowStepState.objects.filter(pk=artifact_id)
            .values_list("run__workflow__workspace_id", flat=True)
            .first()
        )
        return str(row) if row else None

    # ── Unified queue surface (Phase 6a) ─────────────────────────────────────

    def list_pending(self, workspace_id: str) -> list[SignOffItem]:
        from infrastructure.persistence.workspaces.workflows.models import WorkflowStepState

        # A parked AI workflow-email step: waiting_input + a signoff blob whose
        # review_state is still pending/changes_requested. (Decision-node human
        # pauses are also waiting_input but carry no signoff blob, so filtering
        # on the blob's artifact_type excludes them.)
        steps = (
            WorkflowStepState.objects.filter(
                run__workflow__workspace_id=workspace_id,
                status="waiting_input",
                output__signoff__artifact_type=_ARTIFACT_TYPE,
            )
            .select_related("run", "run__workflow")
            .only("id", "output", "started_at", "run__workflow__workspace_id")
        )
        items: list[SignOffItem] = []
        for step in steps:
            signoff = self._signoff(step)
            state_raw = signoff.get("review_state")
            if state_raw and state_raw not in (
                ReviewState.PENDING.value,
                ReviewState.CHANGES_REQUESTED.value,
            ):
                continue
            items.append(
                build_sign_off_item(
                    self,
                    str(step.id),
                    title=signoff.get("subject") or "Workflow email",
                    workspace_id=str(workspace_id),
                    # The step has no created_at; started_at is when it began
                    # waiting for sign-off (the closest "age" signal).
                    created_at=step.started_at,
                )
            )
        return items

    def approve(
        self, artifact_id: str, *, actor_id: str, override_reason: str | None = None
    ) -> None:
        # Approving a parked AI workflow-email SENDS it and RESUMES the run.
        # We reuse the message-node executor for the send (no reimplemented
        # send) and the workflow service's complete_step + the tasks provider
        # for the resume (same mechanism the decision-node ``complete_step``
        # endpoint uses).
        step = self._get_step(artifact_id)
        signoff = self._signoff(step)
        self._send_and_resume(step, signoff)

    def request_changes(
        self, artifact_id: str, *, actor_id: str, codes: tuple[str, ...] = (), note: str = ""
    ) -> None:
        # Keep the step parked (waiting_input) so the run stays paused pending a
        # human fix; the reviewer's note is captured by the queue audit trail.
        self.set_state(artifact_id, ReviewState.CHANGES_REQUESTED)

    def reject(
        self, artifact_id: str, *, actor_id: str, codes: tuple[str, ...] = (), note: str = ""
    ) -> None:
        # Rejecting fails the parked step (maps to ReviewState.REJECTED) so the
        # AI email is never sent and the run does not resume past it.
        self.set_state(artifact_id, ReviewState.REJECTED)

    # ── internals ──────────────────────────────────────────────────────────

    def _send_and_resume(self, step, signoff: dict) -> None:
        from components.workflow.application.service import WorkflowService
        from components.workflow.application.providers.workflow_tasks_provider import (
            get_workflow_tasks_provider,
        )
        from components.workflow.domain.value_objects.workflow_graph import WorkflowGraph
        from components.workflow.infrastructure.adapters.node_actions import (
            execute_node_action,
        )

        run = step.run
        graph = WorkflowGraph(run.workflow.graph)
        node_id = signoff.get("node_id") or step.node_id
        node = graph.node(node_id)
        if node is None:
            raise NotFoundError(
                f"workflow email sign-off node {node_id} not found in graph for run {run.id}"
            )
        config = node.get("config") or {}

        # 1. Send the approved email — reuse the message-node executor. It does
        #    NOT re-park (the park gate lives in the task-level step executor,
        #    not here), so this performs the real deterministic send.
        send_output = execute_node_action(run, node, config)

        # 2. Resume: complete_step marks the step completed, records a step
        #    event, advances current_node_id to the next node, and flips the run
        #    RUNNING. We preserve the approved signoff blob alongside the send
        #    result for the audit/history.
        output = {
            "signoff": {**signoff, "review_state": ReviewState.APPROVED.value},
            "send": send_output,
        }
        service = WorkflowService()
        service.complete_step(run, node_id, output, event_type="completed")

        # 3. Enqueue the next step (or completion) — mirrors the decision-node
        #    ``complete_step`` controller path.
        run.refresh_from_db(fields=["current_node_id", "status"])
        tasks = get_workflow_tasks_provider()
        if run.current_node_id and run.current_node_id != node_id:
            tasks.enqueue_run_step(str(run.id), run.current_node_id)
        else:
            tasks.enqueue_run_complete(str(run.id))

    @staticmethod
    def _signoff(step) -> dict:
        return (step.output or {}).get("signoff") or {}

    @staticmethod
    def _get_step(artifact_id: str):
        from infrastructure.persistence.workspaces.workflows.models import WorkflowStepState

        step = (
            WorkflowStepState.objects.select_related("run", "run__workflow")
            .filter(pk=artifact_id)
            .first()
        )
        if step is None:
            raise NotFoundError(f"workflow email sign-off step {artifact_id} not found")
        return step
