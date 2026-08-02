"""Port: record a draft-PR outcome onto a board Task (finding).

The ``project`` context owns the board ``Task``. When another context (the
integrations VCS capability) opens a draft PR for a finding, the PR link,
provenance event, and card comment are ``project.Task`` data — so ``project``
must own that write (architecture-manifesto Rule 2, architecture-skill C2: a
component never changes data it does not own). This port is the owning-context
surface the integrations adapter delegates to; the integrations context never
touches ``project``'s models.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class RecordFindingDraftPrCommand:
    """The facts needed to stamp a draft PR onto a finding's board card.

    Mirrors exactly what the old in-line ``_record_on_finding`` wrote, so the
    contract (metadata shape, provenance event, comment text) is unchanged.
    """

    workspace_id: str
    task_id: str
    performed_by: str
    acting_agent: str  # e.g. "triage_agent" — attribution for provenance + comment
    pr_url: str
    pr_repo: str
    branch: str


@dataclass(frozen=True)
class RecordFindingDraftPrResult:
    # True when this call performed the write; False when it was a no-op because
    # the task was gone, or a concurrent open already recorded a draft PR (the
    # first PR's record wins — idempotent under concurrency).
    recorded: bool


class RecordFindingDraftPrPort(abc.ABC):
    """Secondary port: append the draft-PR provenance to a finding's Task."""

    @abc.abstractmethod
    def record_draft_pr(self, *, command: RecordFindingDraftPrCommand) -> RecordFindingDraftPrResult:
        """Patch ``metadata.payload.draft_pr``, append a provenance event, and add
        a ``TaskComment`` on the finding's board Task.

        Re-checks ``draft_pr`` right before writing so a concurrent open keeps the
        first PR's record. A task deleted between the caller's precondition and
        this write resolves to ``recorded=False`` (never raises).
        """
        ...
