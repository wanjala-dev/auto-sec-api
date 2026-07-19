"""Build a reviewer-feedback few-shot block for a writing generator (SEE-191).

Phase 6d — "close the feedback loop". A human reviewer's CHANGES_REQUESTED /
REJECTED decisions on past artifacts are captured as eval examples (Phase 6c).
This use case turns the most recent of those, for the SAME workspace + artifact
type, into a compact "reviewers previously flagged these — avoid them" block the
writing tools append to their prompt before generating.

Pure application layer — no Django, no ORM. The store is an injected
``EvalExampleStorePort``; the config is plain module constants.

Design choices:

- **Codes + note, never the rejected content.** We surface WHAT the reviewer
  said was wrong (the reason codes + a truncated note), not the full rejected
  copy. Injecting the bad copy would balloon the prompt and risk the model
  echoing the very text that got rejected.
- **Fail-closed to empty.** Returns ``""`` when the feature is disabled, when
  there's no workspace, or when there are no negatives — so the caller simply
  runs the un-augmented prompt. A feedback lookup must never *add* risk to
  generation.
"""

from __future__ import annotations

from components.agents.application.config import feedback_injection_config as _cfg
from components.agents.application.ports.eval_example_store_port import (
    EvalExampleStorePort,
)
from components.agents.domain.value_objects.eval_example import EvalExample


class GetFewShotNegativesUseCase:
    def __init__(self, store: EvalExampleStorePort) -> None:
        self._store = store

    def execute(self, workspace_id: str, artifact_type: str) -> str:
        """Return a bounded reviewer-feedback block, or ``""`` when there's
        nothing to inject (disabled / no workspace / no negatives)."""
        if not _cfg.FEEDBACK_FEW_SHOT_ENABLED:
            return ""
        if not workspace_id:
            return ""

        negatives = self._store.list_recent_negatives(
            workspace_id=str(workspace_id),
            artifact_type=artifact_type,
            limit=_cfg.FEEDBACK_FEW_SHOT_MAX,
        )
        if not negatives:
            return ""

        lines = [self._render_line(example) for example in negatives]
        lines = [line for line in lines if line]
        if not lines:
            return ""

        header = (
            "REVIEWER FEEDBACK — a human reviewer previously requested changes "
            "or rejected similar drafts for the reasons below. Do NOT repeat "
            "these mistakes:"
        )
        return header + "\n" + "\n".join(lines)

    @staticmethod
    def _render_line(example: EvalExample) -> str:
        codes = ", ".join(str(code) for code in (example.feedback_codes or []) if str(code))
        note = (example.feedback_note or "").strip()
        max_chars = _cfg.FEEDBACK_FEW_SHOT_MAX_NOTE_CHARS
        if len(note) > max_chars:
            note = note[:max_chars].rstrip() + "…"
        if codes and note:
            return f"- [{codes}] {note}"
        if codes:
            return f"- [{codes}]"
        if note:
            return f"- {note}"
        return ""
