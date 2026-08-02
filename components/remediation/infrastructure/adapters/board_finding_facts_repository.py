"""Adapter: read a finding/task's remediation facts from ``project.Task``.

Implements :class:`FindingRemediationFactsPort`. This is the same sanctioned
cross-context read pattern the ``report`` context uses
(``FindingSourcePort`` → ``BoardFindingRepository`` reading ``project.Task``):
the remediation context defines its own port shaped to the gate's need, and this
infrastructure adapter reads the shared ``project`` persistence model. Reading
``infrastructure.persistence.project.models`` is a persistence read, NOT a
``components.project.infrastructure`` import — it does not cross the
component-infrastructure boundary the architecture tests guard.

What each fact maps to on the board Task (see ADR 0012 grounding):

- ``draft_pr_url`` ← ``metadata.payload.draft_pr.url`` — written once when the
  draft PR is *opened* (``open_draft_pr_use_case``). This proves a PR exists, not
  that it merged; the gate combines it with an explicit operator "applied"
  confirmation (merge-detection is the P4 gap).
- ``finding_resolved`` ← a resolved marker on the task
  (``metadata.triage.status == "resolved"`` or ``metadata.payload.resolved``).
  Today nothing flips this — the board triage tops out at ``"triaged"`` — so it
  reads ``False`` until the resolved-transition trigger lands (P4). The gate is
  correct regardless: no resolved marker ⇒ the gate refuses.
- ``provenance_event_ref`` ← a reference to the newest ``metadata.provenance``
  event (its ``action``/``at``), so the corpus entry links to the board fact.
- ``finding_kind`` ← ``source_type`` with the ``ai.`` prefix stripped, matching
  ``persist_finding_as_task``'s ``action_type`` convention.
"""

from __future__ import annotations

from components.remediation.application.ports.finding_remediation_facts_port import (
    FindingRemediationFacts,
    FindingRemediationFactsPort,
)


def _derive_kind(source_type: str) -> str:
    return source_type[3:] if source_type.startswith("ai.") else source_type


def _newest_provenance_ref(metadata: dict) -> str:
    provenance = metadata.get("provenance") or {}
    events = provenance.get("events") or []
    if not events:
        return ""
    last = events[-1]
    actor = last.get("actor", "")
    at = last.get("at", "")
    return f"{actor}@{at}" if (actor or at) else ""


def _is_resolved(metadata: dict) -> bool:
    triage = metadata.get("triage") or {}
    if str(triage.get("status", "")).lower() == "resolved":
        return True
    payload = metadata.get("payload") or {}
    return bool(payload.get("resolved"))


class BoardFindingFactsRepository(FindingRemediationFactsPort):
    def get_facts(self, *, workspace_id: str, finding_task_id: str) -> FindingRemediationFacts:
        from infrastructure.persistence.project.models import Task

        # Workspace-scoped lookup — a task from another workspace resolves to
        # exists=False and never leaks its finding (tenant isolation).
        row = (
            Task.objects.filter(id=finding_task_id, workspace_id=workspace_id)
            .only("id", "workspace_id", "source_type", "metadata")
            .first()
        )
        if row is None:
            return FindingRemediationFacts(
                finding_task_id=finding_task_id,
                workspace_id=workspace_id,
                exists=False,
                source_type="",
                finding_kind="",
                finding_fingerprint="",
                draft_pr_url=None,
                finding_resolved=False,
                provenance_event_ref="",
            )

        metadata = row.metadata or {}
        payload = metadata.get("payload") or {}
        draft_pr = payload.get("draft_pr") or {}
        source_type = row.source_type or ""

        return FindingRemediationFacts(
            finding_task_id=str(row.id),
            workspace_id=str(row.workspace_id),
            exists=True,
            source_type=source_type,
            finding_kind=_derive_kind(source_type),
            finding_fingerprint=str(payload.get("fingerprint") or metadata.get("fingerprint") or ""),
            draft_pr_url=(draft_pr.get("url") or None),
            finding_resolved=_is_resolved(metadata),
            provenance_event_ref=_newest_provenance_ref(metadata),
        )
