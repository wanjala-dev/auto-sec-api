"""Command DTO: propose recording a remediation entry.

A *proposal* — cheap and open (ADR 0012 D1: "you can only propose"). It carries
what the caller believes about the fix; the gated use case independently
re-verifies the three conditions before anything is written. Note ``pr_applied``:
because merge-detection is not built, the caller must explicitly confirm the PR
was applied (merged) — the gate cross-checks this against the opened draft PR
but will not infer it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class RecordRemediationEntryCommand:
    workspace_id: UUID
    # The finding/board task the fix remediates (the provenance link).
    finding_task_id: str
    # The sign-off artifact identifying the approval for this remediation.
    sign_off_artifact_type: str
    sign_off_artifact_id: str
    # Explicit operator confirmation that the draft PR was applied (merged).
    # Required because merge-detection is not yet built (P4 gap).
    pr_applied: bool
    applied_pr_url: str
    # The RAW fix (D3: never rendered HTML) + language.
    code: str
    language: str = ""
    title: str = ""
    summary: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
