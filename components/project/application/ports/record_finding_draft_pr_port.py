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

# ── Canonical draft-PR metadata location ────────────────────────────────────
# The ONE definition of where the draft-PR record lives on a finding Task's
# ``metadata`` JSON column. The writer (``OrmRecordFindingDraftPrRepository``)
# and every reader — the remediation reconciler's candidate query, the
# task-lookup seam — MUST address the path through these helpers. Before this,
# the reconciler hand-typed ``metadata__payload__draft_pr`` while the writer
# hand-built the nested dict, so a writer-side move of the record would have
# silently emptied the reconciler's candidate set. The round-trip integration
# test (components/remediation/tests/integration/test_reconcile_roundtrip_guard
# .py) locks writer and reader together through this single definition.
#
# Lives in the PORT module (not the ORM repository) deliberately: the metadata
# shape is part of the recording CONTRACT, and ``application/ports`` is the one
# surface other contexts may import (architecture-manifesto Rule 3) — the
# reconciler could never reach a helper inside ``project``'s infrastructure.

DRAFT_PR_METADATA_PATH: tuple[str, ...] = ("payload", "draft_pr")

DRAFT_PR_JSON_LOOKUP: str = "metadata__" + "__".join(DRAFT_PR_METADATA_PATH)


def draft_pr_candidate_filter() -> dict[str, bool]:
    """ORM filter kwargs selecting Tasks that CARRY a draft-PR record.

    Use as ``Task.objects.filter(**draft_pr_candidate_filter())`` — derived
    from ``DRAFT_PR_METADATA_PATH`` so the query can never drift from the
    written shape. (Plain strings only — no Django import; the application
    layer stays framework-free.)
    """
    return {f"{DRAFT_PR_JSON_LOOKUP}__isnull": False}


def get_draft_pr(metadata: object) -> dict:
    """Read the draft-PR record off a Task's ``metadata`` (missing/malformed → ``{}``)."""
    node = metadata
    for key in DRAFT_PR_METADATA_PATH:
        if not isinstance(node, dict):
            return {}
        node = node.get(key)
    return node if isinstance(node, dict) else {}


def set_draft_pr(metadata: dict, record: dict) -> None:
    """Write the draft-PR record at the canonical path, creating parent nodes.

    Mutates ``metadata`` in place (the writer re-assigns the column afterwards).
    """
    node = metadata
    for key in DRAFT_PR_METADATA_PATH[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[DRAFT_PR_METADATA_PATH[-1]] = record


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
