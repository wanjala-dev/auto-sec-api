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

# ── Canonical stored-diff bound ─────────────────────────────────────────────
# The ONE definition of how large a stored draft-PR diff may get. Part of the
# recording CONTRACT (like the metadata path above), not an implementation
# detail of any single writer: the open step bounds the diff it computes from
# the advisor's proposal, and the legacy backfill bounds the diff it reads back
# from the code host. Both go through :func:`bound_diff`, so a stored diff can
# never depend on which writer produced it — the HUD renders legacy and new
# records identically.

DRAFT_PR_DIFF_MAX_CHARS: int = 12_000

DRAFT_PR_DIFF_TRUNCATION_MARKER: str = "\n… (diff truncated)"


def bound_diff(diff: str, *, max_chars: int = DRAFT_PR_DIFF_MAX_CHARS) -> str:
    """Clamp ``diff`` to the stored-record bound, marking it when truncated."""
    text = diff or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + DRAFT_PR_DIFF_TRUNCATION_MARKER


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
    #: "verified" | "unverified" | "" — the confidence LABEL the engine stamped on
    #: the PR. Recorded on the card so the HUD renders "FIX DRAFTED — UNVERIFIED"
    #: (never a bare dead-end flag) and the comment carries the warning.
    verification: str = ""
    #: The named evidence gap when ``verification == "unverified"``.
    verification_gap: str = ""
    #: The patch that went into the PR — the flagged file's path + the bounded
    #: unified diff + the advisor's change summary. Persisted so the HUD renders
    #: the code change INLINE on the finding/board callouts (the PR link is the
    #: secondary action, not the only review surface).
    path: str = ""
    diff: str = ""
    change_summary: str = ""


@dataclass(frozen=True)
class AttachDraftPrPatchCommand:
    """Attach the reviewed patch to a draft-PR record that already exists.

    The *repair* counterpart to :class:`RecordFindingDraftPrCommand`. Records
    opened before the open step began persisting the patch carry a ``draft_pr``
    with a ``url`` but no ``diff``, so the HUD degrades to a bare "VIEW DRAFT PR"
    link. This command fills exactly that gap — it never creates a record, never
    touches the ``url``/``repo``/``branch``/``verification`` facts the open step
    established, and never adds a card comment (the PR was already announced).

    ``reason`` is stamped onto the provenance event so the board shows WHY the
    card changed outside a normal open (e.g. ``"legacy_patch_backfill"``).
    ``pr_state`` / ``merged`` record the PR's live lifecycle at attach time — a
    legacy PR may since have merged or closed, and the record says so honestly
    rather than implying it is still awaiting review.
    """

    workspace_id: str
    task_id: str
    path: str
    diff: str
    change_summary: str = ""
    pr_state: str = ""
    merged: bool = False
    reason: str = "patch_backfill"


@dataclass(frozen=True)
class AttachDraftPrPatchResult:
    """Outcome of an attach attempt — ``attached`` false is a SKIP, never an error.

    ``reason`` names the skip so the caller can count outcomes:
    ``"task_not_found"``, ``"no_draft_pr_record"``, ``"already_has_diff"``
    (the idempotent re-run case), or ``"empty_diff"`` (refused — a fabricated or
    empty patch is never stored).
    """

    attached: bool
    reason: str = ""


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

    @abc.abstractmethod
    def attach_draft_pr_patch(self, *, command: AttachDraftPrPatchCommand) -> AttachDraftPrPatchResult:
        """Fill in the patch on an EXISTING ``draft_pr`` record, leaving it otherwise intact.

        Idempotent by construction: a record that already carries a non-empty
        ``diff`` is left untouched (``attached=False``, ``reason="already_has_diff"``),
        so the backfill is safe to re-run. An absent task or a task with no
        ``draft_pr`` record likewise resolves to a skip — never raises.
        """
        ...
