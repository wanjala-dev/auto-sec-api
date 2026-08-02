"""Port: read-only lookups against the board ``project.Task`` the AI surfaces need.

The ``project`` context owns ``Task``; other contexts (today the ``agents``
context: specialist persistence + AI-governance) read a handful of narrow,
workspace-scoped facts off it. This port is the sanctioned seam for those reads
so callers stop reaching into ``infrastructure.persistence.project.models``
directly (Rule 2 / architecture-skill C3: read another context's data through a
port, never its ORM).

It carries exactly the two reads the current consumers make:

1. ``find_by_idempotency`` — the replay short-circuit in
   ``persist_finding_as_task``: a finding with the same
   ``(workspace_id, source_type, metadata.idempotency_key)`` already exists →
   return its task id (caller treats a hit as a no-op replay), else ``None``.

2. ``list_draft_pr_findings`` — the HITL approval ledger in
   ``ai_governance_service.hitl_ledger``: every AI-finding task in the workspace
   that carries a ``metadata.payload.draft_pr.url`` (each opened draft PR IS a
   granted human approval). Returns a frozen DTO per finding — never an ORM row.

Every method is workspace-scoped: a task id / row from another workspace is
never returned (tenant isolation).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DraftPrFinding:
    """A finding/board task carrying an opened draft PR (HITL approval trail).

    Shapes the ``metadata.payload.draft_pr`` slice ``compute_hitl_ledger`` reads.
    ``opened_at`` is passed through as the raw stored value (a naive/aware ISO
    string written with ``datetime.now(UTC).isoformat()``) — the consumer's
    ``_parse_iso`` handles the naive/aware normalization + window filtering, so
    this port does no date coercion of its own.
    """

    task_id: UUID
    title: str
    url: str
    repo: str
    branch: str
    opened_by: str | None
    opened_at: str | None


class TaskLookupPort(ABC):
    @abstractmethod
    def find_by_idempotency(self, *, workspace_id: str, source_type: str, key: str) -> UUID | None:
        """Return the id of an existing finding task with this idempotency key.

        Matches on ``(workspace_id, source_type, metadata.idempotency_key)`` —
        the exact tuple ``persist_finding_as_task`` dedups on. Returns the task
        id on a hit (caller replays as a no-op), ``None`` on a miss. An empty
        ``key`` never matches (returns ``None``); callers with no idempotency
        contract skip the check entirely.
        """

    @abstractmethod
    def list_draft_pr_findings(self, *, workspace_id: str) -> list[DraftPrFinding]:
        """Return every AI-finding task in the workspace carrying a draft PR.

        Scans ``source_type`` starting ``ai.`` and yields one
        :class:`DraftPrFinding` per task whose ``metadata.payload.draft_pr`` has
        a non-empty ``url``. Not window-filtered here — the consumer windows on
        ``opened_at`` (approval events are sparse; a stored PR with an
        unparseable date must still surface as ``undated``, not be dropped).
        """
