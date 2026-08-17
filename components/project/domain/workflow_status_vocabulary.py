"""Canonical workflow-status vocabulary (ADR 0030, Model A).

ONE place defines the six canonical lanes and the column-title -> status
mapping. Both the P1 backfill migration
(``infrastructure/persistence/project/migrations/0008_*``) and the runtime
dual-write bridge (``components/project/infrastructure/adapters/
django_workflow_status_sync_bridge.py``) resolve titles through this module —
never through a private copy (``dry-reuse.md``).

Pure domain: strings and tuples only. No Django, no ORM — the migration and
the bridge each wrap it with their own persistence plumbing (historical
models + pinned alias on one side, concrete models on the other).

STABILITY: migration 0008 imports this module, so its behaviour on the
canonical set and the legacy/AI title mappings is part of the migration's
contract. Extending the vocabulary (a new alias) is safe; renaming or
re-categorizing an existing entry changes what a fresh install's backfill
produces and must be treated as a deliberate, reviewed change.
"""

from __future__ import annotations

# Category axis (Linear-style coarse states that survive renames).
CATEGORY_BACKLOG = "backlog"
CATEGORY_UNSTARTED = "unstarted"
CATEGORY_STARTED = "started"
CATEGORY_COMPLETED = "completed"
CATEGORY_CANCELED = "canceled"

CATEGORIES = (
    CATEGORY_BACKLOG,
    CATEGORY_UNSTARTED,
    CATEGORY_STARTED,
    CATEGORY_COMPLETED,
    CATEGORY_CANCELED,
)

#: A column title the mapping does not know resolves to a team-local status
#: with this category (ADR 0030 P1: "exceptions logged").
FALLBACK_CATEGORY = CATEGORY_STARTED

#: The canonical seed — the 6-lane set the quick-wins PRs converged every
#: board on: (name, category, order). Testing is deliberately ``started``;
#: everything else maps 1:1 onto its category.
CANONICAL_STATUSES: tuple[tuple[str, str, int], ...] = (
    ("Backlog", CATEGORY_BACKLOG, 1),
    ("Todo", CATEGORY_UNSTARTED, 2),
    ("In Progress", CATEGORY_STARTED, 3),
    ("Testing", CATEGORY_STARTED, 4),
    ("Complete", CATEGORY_COMPLETED, 5),
    ("Canceled", CATEGORY_CANCELED, 6),
)

_CANONICAL_BY_LOWER_TITLE = {name.lower(): name for name, _category, _order in CANONICAL_STATUSES}

#: Non-canonical column titles -> canonical status name (lower-cased keys).
#: - "Done": the user-legacy seventh lane (project migration 0006 merged most).
#: - The AI vocabularies: the ADR 0030 P3 table — the "AI Findings" project
#:   board (Suggested / Under Review / Accepted / Dismissed) and the lazily
#:   created Agents team-board lanes (Triage / Optimize).
_ALIAS_BY_LOWER_TITLE = {
    "done": "Complete",
    "suggested": "Todo",
    "under review": "In Progress",
    "triage": "In Progress",
    "optimize": "In Progress",
    "accepted": "Complete",
    "dismissed": "Canceled",
}


def resolve_status_name_for_column_title(title: str | None) -> str | None:
    """Map a board-column title to its canonical status name.

    Matching is case-insensitive and whitespace-tolerant so an operator's
    hand-typed "in progress" lands on the canonical lane instead of minting a
    duplicate vocabulary. Returns ``None`` for a title the vocabulary does not
    know — the caller creates a team-local status with
    :data:`FALLBACK_CATEGORY` and logs the exception.
    """
    key = (title or "").strip().lower()
    if not key:
        return None
    return _CANONICAL_BY_LOWER_TITLE.get(key) or _ALIAS_BY_LOWER_TITLE.get(key)
