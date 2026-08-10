"""Port: read the finding (board Task) facts the draft-PR flow reasons about.

The board ``Task`` is owned by the ``project`` context. The integrations VCS
draft-PR capability only *reads* it — so it does so read-only, through this port,
never by importing ``project``'s models (architecture-manifesto Rule 2 /
architecture-skill C3). This is the same sanctioned pattern the ``report`` and
``remediation`` contexts use (``FindingSourcePort`` / ``FindingRemediationFactsPort``
→ an infrastructure adapter that reads ``project.Task``).

The adapter enforces the source-type gate (``ai.log_watch``) and workspace scope;
the use case reasons about triage/payload state from the returned metadata exactly
as it did when it read the ORM row directly, so the contract is unchanged.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionableFinding:
    """The read-only slice of a finding's board Task the draft-PR flow needs.

    Carries the same three things the use case previously read off the ORM row:
    the id (for branch naming, deep links, the recorder write), the title (PR
    title + notification verb), and the full metadata blob (triage status,
    needs_human flag, and the evidence ``payload`` the advisor patches from) —
    plus ``source_type``, which the use case branches on to pick the patch
    strategy (log traceback heuristics vs the SAST location pass-through).
    """

    id: str
    title: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_type: str = ""


@dataclass(frozen=True)
class DraftPrPatchGap:
    """A finding whose draft-PR record exists but carries no reviewable patch.

    The unit of work for the legacy-record backfill: everything needed to ask the
    code host for the PR's patch (``pr_url``, plus the ``repo`` the record itself
    names) and to write the answer back to the right card (``workspace_id`` +
    ``task_id``). Deliberately carries no metadata blob — the backfill reasons
    about nothing else on the finding.
    """

    workspace_id: str
    task_id: str
    pr_url: str
    repo: str = ""


class FindingFactsPort(abc.ABC):
    @abc.abstractmethod
    def get_actionable_finding(self, *, workspace_id: str, task_id: str) -> ActionableFinding | None:
        """Return the draft-PR-actionable finding ``task_id`` on ``workspace_id``'s
        board (``ai.log_watch`` or ``ai.code_security``), or ``None`` when there is
        no such finding (absent, wrong workspace, wrong source type, or a malformed
        id). Never raises on a bad id — resolves to ``None``, which the use case
        maps to the ``finding_not_found`` precondition."""
        ...

    @abc.abstractmethod
    def count_open_draft_prs(self, *, workspace_id: str, source_type: str, repo: str) -> int:
        """How many of ``source_type``'s findings on this workspace's board carry an
        OPEN (recorded, not yet resolved) draft PR against ``repo``. Feeds the ADR
        0019 D5 per-repo SAST PR throttle — merged PRs resolve their finding via the
        remediation reconciler and stop counting."""
        ...

    @abc.abstractmethod
    def list_draft_pr_patch_gaps(self, *, workspace_id: str = "", limit: int = 500) -> tuple[DraftPrPatchGap, ...]:
        """Findings carrying a draft-PR record with a ``url`` but no stored ``diff``.

        These are the records written before the open step began persisting the
        patch — the HUD can only show them as a bare link. Empty ``workspace_id``
        scans every workspace (the one-off repair sweep); a set one scopes the
        sweep. Ordered oldest-first so a limited run makes deterministic progress.
        """
        ...
