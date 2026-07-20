"""Value objects for workspace snapshots.

A workspace snapshot is the canonical text representation of a workspace —
the material fed into the embedding pipeline and consulted by the deep agent
at retrieval time.  Snapshots are pure data: no Django imports, no I/O.

The snapshot is broken into *sections* so we can reason about which parts of
a workspace a retrieved chunk came from (identity, mission, team, ops,
activity) rather than treating the whole workspace as one opaque blob.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkspaceSnapshotSection:
    """One named section of a workspace snapshot.

    ``key`` is a stable machine slug (``identity``, ``mission``, ``team``, …)
    surfaced in chunk metadata so retrieval can filter by section.

    ``title`` is the human-facing header written into the chunk body.

    ``body`` is free text.  Empty bodies are filtered out by the builder —
    a section that exists but is blank is noise, not signal.
    """

    key: str
    title: str
    body: str

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("WorkspaceSnapshotSection.key is required")
        if not self.title:
            raise ValueError("WorkspaceSnapshotSection.title is required")
        if not self.body or not self.body.strip():
            raise ValueError("WorkspaceSnapshotSection.body must be non-empty")


@dataclass(frozen=True)
class WorkspaceSnapshotInput:
    """Raw workspace facts the snapshot builder consumes.

    This dataclass is the boundary between infrastructure (which reads the
    Django ORM) and the domain builder (which knows nothing about Django).
    Adapters build this from the ORM; the builder turns it into text.
    """

    workspace_id: str
    workspace_name: str
    workspace_type: str = ""
    # Security domains the workspace operates across (Cloud, Endpoint, …) —
    # replaces the wanjala-era single sector FK (sectors→domains rename).
    domain_names: tuple[str, ...] = ()
    story: str = ""
    vision: str = ""
    mission: str = ""
    privacy: str = ""
    status: str = ""
    default_currency: str = ""
    contact_email: str = ""
    categories: tuple[str, ...] = ()
    subcategories: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    contribution_means: tuple[str, ...] = ()
    member_count: int = 0
    active_member_count: int = 0
    follower_count: int = 0
    team_count: int = 0
    # Tier 2 #5 — recent activity rollup (last 30 days).  Counts only;
    # individual rows live behind specialist agents.  The
    # ``..._total_30d`` strings are pre-formatted ("USD 12,345.00") so
    # the domain builder stays unaware of currency formatting rules.
    recent_donation_count_30d: int = 0
    recent_donation_total_30d: str = ""
    recent_new_recipient_count_30d: int = 0
    recent_new_campaign_count_30d: int = 0
    recent_new_grant_decision_count_30d: int = 0
    recent_new_project_count_30d: int = 0
    # Tier 2 #6 — top entities (current state).  Each row is a single
    # pre-formatted line: "Alice Mwangi — USD 12,400 lifetime".  The
    # adapter chooses the format; the builder just renders bullets.
    top_donors: tuple[str, ...] = ()
    top_recipients: tuple[str, ...] = ()
    active_campaigns: tuple[str, ...] = ()
    open_grants: tuple[str, ...] = ()
    active_projects: tuple[str, ...] = ()
    # Tier 3 #14 — workspace members by name.  Indexing member names
    # closes the "Find <person>" routing gap: with members in the
    # embedding index, hybrid search surfaces a member chunk for
    # member-shaped queries and the planner can prefer user_agent
    # over donation_agent / sponsorship_agent.  Format per row is
    # "First Last — Role" (no email; PII stays out of the index).
    top_members: tuple[str, ...] = ()
    created_at_iso: str = ""
    updated_at_iso: str = ""

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("WorkspaceSnapshotInput.workspace_id is required")
        if not self.workspace_name:
            raise ValueError("WorkspaceSnapshotInput.workspace_name is required")


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Built snapshot: sections + a stable content hash.

    ``content_hash`` is computed from the sections' bodies only — purely a
    function of the *indexable* text.  Callers compare it to the hash stored
    in the last indexed chunk; if identical, re-embedding is a no-op.
    """

    workspace_id: str
    sections: tuple[WorkspaceSnapshotSection, ...]
    content_hash: str

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("WorkspaceSnapshot.workspace_id is required")
        if not self.content_hash:
            raise ValueError("WorkspaceSnapshot.content_hash is required")

    def is_empty(self) -> bool:
        return not self.sections

    @staticmethod
    def compute_hash(sections: tuple[WorkspaceSnapshotSection, ...]) -> str:
        """Stable SHA-256 hash of section bodies (order-sensitive)."""
        hasher = hashlib.sha256()
        for section in sections:
            hasher.update(section.key.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(section.body.encode("utf-8"))
            hasher.update(b"\x01")
        return hasher.hexdigest()


@dataclass(frozen=True)
class ReindexResult:
    """Outcome of a workspace reindex call."""

    STATUS_INDEXED = "indexed"
    STATUS_SKIPPED = "skipped"
    STATUS_FAILED = "failed"
    STATUS_EMPTY = "empty"

    status: str
    workspace_id: str
    chunks_written: int = 0
    content_hash: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        allowed = {
            self.STATUS_INDEXED,
            self.STATUS_SKIPPED,
            self.STATUS_FAILED,
            self.STATUS_EMPTY,
        }
        if self.status not in allowed:
            raise ValueError(f"Invalid ReindexResult status: {self.status}")
