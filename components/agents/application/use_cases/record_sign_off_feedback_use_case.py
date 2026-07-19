"""Turn a reviewer sign-off decision into a labeled eval example (SEE-190).

Phase 6c of the Verification-Assisted Sign-Off Spine. The
``sign_off_feedback_handler`` subscribes to ``SignOffDecisionRecorded`` and
drives this use case; the use case applies the label policy, captures the
generator's output snapshot, and stores the example through the
``EvalExampleStorePort``.

Label policy (which decisions become examples):

- ``approved`` + non-RED band  → **skip** (a rubber-stamp GREEN/AMBER approve
  carries no signal and would dominate + bias the set). Returns ``None``,
  stores nothing.
- ``approved`` + RED band       → **positive** example (``APPROVED_OVERRIDE``):
  reviewed hard, approved anyway.
- ``changes_requested``         → **negative** example; the codes + note are the
  label ("what the generator got wrong").
- ``rejected``                  → **negative** example.

Framework-free — no Django, no ORM. The store is an injected port; the capture
seam is an injected callable ``(artifact_type, artifact_id) -> dict | None`` so
the use case never reaches into another context.
"""

from __future__ import annotations

from typing import Callable

from components.agents.application.ports.eval_example_store_port import (
    EvalExampleStorePort,
)
from components.agents.domain.value_objects.eval_example import (
    EvalExample,
    FeedbackDecision,
)

CaptureFn = Callable[[str, str], "dict | None"]


class RecordSignOffFeedbackUseCase:
    def __init__(
        self,
        store: EvalExampleStorePort,
        capture: CaptureFn | None = None,
    ) -> None:
        self._store = store
        # Optional — resolves the artifact's generated output + grounding
        # snapshot. May legitimately return None (artifact type carries no
        # capturable AI output); the example is then metadata-only.
        self._capture = capture

    def execute(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        decision: str,
        risk_band: str,
        reason_codes,
        note: str,
        actor_id,
        workspace_id,
    ) -> str | None:
        """Store one eval example for a decision, or ``None`` when the label
        policy skips it (or the store deduplicated an idempotent replay)."""
        label = self._label_for(decision, risk_band)
        if label is None:
            return None

        codes = [str(code) for code in (reason_codes or [])]
        snapshot = (self._capture(artifact_type, artifact_id) if self._capture else None) or {}

        input_data = {
            "grounding_texts": snapshot.get("grounding_texts", []),
            "prompt_id": snapshot.get("prompt_id", ""),
        }
        expected_output: dict = {
            "decision": decision,
            "codes": codes,
            "note": note or "",
        }
        # Negative examples carry the rejected copy so the eval can see what
        # "wrong" looked like; a positive override doesn't need it.
        generated_content = snapshot.get("generated_content")
        if (
            label in (FeedbackDecision.CHANGES_REQUESTED, FeedbackDecision.REJECTED)
            and generated_content
        ):
            expected_output["generated_content"] = generated_content

        example = EvalExample(
            dataset_name=f"feedback-{artifact_type}",
            case_id=f"{artifact_type}:{artifact_id}",
            category=codes[0] if codes else "general",
            goal=self._goal_for(artifact_type),
            feedback_decision=label,
            artifact_type=artifact_type,
            artifact_id=str(artifact_id),
            input_data=input_data,
            expected_output=expected_output,
            feedback_codes=codes,
            feedback_note=note or "",
            risk_band=risk_band or "",
            reviewer_id=str(actor_id) if actor_id else "",
            workspace_id=str(workspace_id) if workspace_id else "",
        )
        return self._store.add_example(example)

    # ── label policy ─────────────────────────────────────────────────────────

    @staticmethod
    def _label_for(decision: str, risk_band: str) -> FeedbackDecision | None:
        if decision == "approved":
            # Only a careful RED-band override carries signal; skip rubber stamps.
            if (risk_band or "").lower() == "red":
                return FeedbackDecision.APPROVED_OVERRIDE
            return None
        if decision == "changes_requested":
            return FeedbackDecision.CHANGES_REQUESTED
        if decision == "rejected":
            return FeedbackDecision.REJECTED
        return None

    @staticmethod
    def _goal_for(artifact_type: str) -> str:
        label = (artifact_type or "artifact").replace("_", " ").strip()
        return f"Generate a {label} that passes human sign-off review."
