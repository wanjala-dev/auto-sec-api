"""Port: read the remediation-relevant facts about a finding/board task.

The entry-gate needs three things it does NOT own, read-only (architecture skill
C3): (1) whether a draft PR was opened for the fix, (2) whether the finding is
resolved, (3) a provenance-event reference to link the corpus entry to the board
fact. The adapter reads the ``project.Task`` metadata for these — the same
sanctioned "read another context's board via my own port + persistence read"
pattern the ``report`` context uses (``FindingSourcePort`` /
``BoardFindingRepository``).

Crucially, this port exposes ``draft_pr_url`` (the *opened* PR) but NOT an
"applied/merged" boolean — because **merge-detection does not exist yet** (no PR
webhook, no PR-state poll; ``metadata.payload.draft_pr`` is written once at
open-time and never updated). The gate therefore takes "applied" as an explicit
operator confirmation and cross-checks it against the opened draft PR here; it
never *infers* applied from a draft PR merely being open. Building real
merge-detection (a ``VcsPort.get_pull_request`` / GitHub webhook) is the P4
follow-up.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FindingRemediationFacts:
    """The read-only slice of a finding/task the gate reasons about."""

    # The board task / finding identity + tenant.
    finding_task_id: str
    workspace_id: str
    exists: bool
    # Retrieval keys carried from the finding (source_type / derived kind).
    source_type: str
    finding_kind: str
    finding_fingerprint: str
    # (1) The draft PR opened for the fix, if any: {url, repo, branch, ...}.
    draft_pr_url: str | None
    # (2) Whether the finding is observed resolved (board triage + finding SSOT).
    finding_resolved: bool
    # (3) A reference to the newest provenance event (link, don't copy).
    provenance_event_ref: str


class FindingRemediationFactsPort(ABC):
    @abstractmethod
    def get_facts(self, *, workspace_id: str, finding_task_id: str) -> FindingRemediationFacts:
        """Return the gate-relevant facts for a finding/task in a workspace.

        Always workspace-scoped: a task id from another workspace resolves to
        ``exists=False`` (tenant isolation), never leaks another tenant's finding.
        """
