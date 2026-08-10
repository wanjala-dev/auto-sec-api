"""Port: record an opened draft PR onto the finding it fixes.

The draft-PR link + provenance + card comment are ``project.Task`` data. The
integrations context does not own that data, so it does not write it directly
(architecture-manifesto Rule 2 / architecture-skill C2 — a component never changes
data it does not own). Instead the use case depends on this port; the adapter
delegates to ``project``'s application surface, which performs the actual Task
write. The integrations context never imports ``project``'s models.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc


class FindingPrRecorderPort(abc.ABC):
    @abc.abstractmethod
    def record_draft_pr(
        self,
        *,
        workspace_id: str,
        task_id: str,
        performed_by: str,
        acting_agent: str,
        pr_url: str,
        pr_repo: str,
        branch: str,
        verification: str = "",
        verification_gap: str = "",
        path: str = "",
        diff: str = "",
        change_summary: str = "",
    ) -> None:
        """Stamp the opened draft PR onto the finding's board card.

        Idempotent under concurrency (the owning write re-checks ``draft_pr`` before
        writing) and a no-op if the task was deleted since the precondition check —
        never raises for either case."""
        ...

    @abc.abstractmethod
    def attach_draft_pr_patch(
        self,
        *,
        workspace_id: str,
        task_id: str,
        path: str,
        diff: str,
        change_summary: str = "",
        pr_state: str = "",
        merged: bool = False,
        reason: str = "patch_backfill",
    ) -> tuple[bool, str]:
        """Fill the patch into a draft-PR record the open step already wrote.

        The repair path for records created before the open step persisted the
        diff. Returns ``(attached, reason)`` — ``attached=False`` is always a
        SKIP with a named reason (``"already_has_diff"`` on a re-run,
        ``"no_draft_pr_record"``, ``"task_not_found"``, ``"empty_diff"``), never
        an error. The owning context performs the write; the record's identity
        facts are never rewritten."""
        ...
