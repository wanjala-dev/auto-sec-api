"""Port: record a fix PREVIEW onto a board Task (finding) — ADR 0012 P6.

Preview-before-commit (ADR 0012 P6, from bufferoverflowexception's save-vs-preview):
the operator sees the grounded proposed fix + its grounding sources BEFORE any draft
PR is opened. That preview is ``project.Task`` data (the finding's card), so — exactly
like the draft-PR record (``RecordFindingDraftPrPort``) — the ``project`` context owns
the write; the integrations preview flow delegates here rather than touching
``project``'s models (architecture-manifesto Rule 2 / architecture-skill C2).

Writing ``metadata.payload.proposed_patch`` also feeds the reconcile capture
(``reconcile_remediations_tasks._build_candidate`` already reads ``proposed_patch``),
so a previewed-then-merged fix carries its real patch code into the gated corpus
entry — not just the free-text ``suggested_fix``.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecordFindingPreviewCommand:
    """The facts needed to stamp a proposed-fix preview onto a finding's board card.

    ``grounding`` is a list of light dicts describing the vetted prior fixes that
    grounded the proposal (title/summary/kind/score/rating) — provenance the operator
    sees, never executable content. ``code`` is the PROPOSED patch (the operator's own
    repo code, shown as it would appear in the PR).
    """

    workspace_id: str
    task_id: str
    performed_by: str
    acting_agent: str  # e.g. "triage_agent" — attribution for provenance + comment
    path: str
    code: str
    language: str
    change_summary: str
    grounding: tuple[dict, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RecordFindingPreviewResult:
    # True when this call performed the write; False when it was a no-op because the
    # task was gone, or a draft PR was already opened (nothing left to preview).
    recorded: bool


class RecordFindingPreviewPort(abc.ABC):
    """Secondary port: append a proposed-fix preview to a finding's Task."""

    @abc.abstractmethod
    def record_preview(self, *, command: RecordFindingPreviewCommand) -> RecordFindingPreviewResult:
        """Patch ``metadata.payload.proposed_patch``, append a provenance event, and
        add a ``TaskComment`` describing the preview.

        Does NOT touch ``draft_pr`` and never opens a PR — preview grounds, it never
        authorises (D2). A task deleted since the caller's precondition resolves to
        ``recorded=False`` (never raises); a finding that already has a draft PR is a
        ``recorded=False`` no-op (there is nothing left to preview)."""
        ...
