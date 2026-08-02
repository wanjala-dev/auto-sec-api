"""Port: enumerate findings that carry an OPEN, unresolved draft PR (ADR 0012 P4a).

The reconciler's fan-out input: findings where a fix was *proposed* (a
``draft_pr`` was written onto the board Task) but not yet reconciled (the finding
is not resolved and has no RemediationEntry). These are the candidates whose merge
status is worth checking.

A read-only query over the board (``project.Task``), so it lives behind a port the
remediation context owns; the infra adapter reads ``project.Task`` with an
``.iterator(chunk_size=…)`` scan (performance rule §5 — never materialise the whole
board). Returns lightweight rows, not entities — the reconciler re-reads full facts
per candidate through ``FindingRemediationFactsPort`` before acting.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class OpenDraftPrFinding:
    """A candidate finding for the reconciler: it has a draft PR and is not yet
    resolved. ``pr_url`` / ``repo`` come straight off ``metadata.payload.draft_pr``."""

    workspace_id: str
    finding_task_id: str
    repo: str
    pr_url: str


class OpenDraftPrFindingsPort(ABC):
    @abstractmethod
    def iter_open_draft_pr_findings(self, *, chunk_size: int = 500) -> Iterator[OpenDraftPrFinding]:
        """Yield every finding carrying a draft PR that is not yet resolved, across
        all workspaces (the beat task fans out over them). Streams via the ORM
        iterator so a large board never loads into memory at once."""
