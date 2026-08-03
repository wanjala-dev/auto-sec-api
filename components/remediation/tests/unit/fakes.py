"""In-memory fakes for the remediation ports — no DB, no framework.

Let the gate be exercised as pure orchestration: the store records what it was
asked to save (so a test can assert the gate wrote nothing on refusal), and the
two read-ports return scripted facts.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from components.remediation.application.ports.finding_remediation_facts_port import (
    FindingRemediationFacts,
    FindingRemediationFactsPort,
)
from components.remediation.application.ports.remediation_entry_store_port import (
    RemediationEntryStorePort,
)
from components.remediation.application.ports.sign_off_gate_port import SignOffGatePort
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.domain.services.remediation_ranking_policy import (
    RemediationRankingPolicy,
)


class FakeStore(RemediationEntryStorePort):
    def __init__(self) -> None:
        self.saved: list[RemediationEntry] = []

    def _replace(self, entry: RemediationEntry) -> None:
        self.saved = [e for e in self.saved if e.id != entry.id]
        self.saved.append(entry)

    def save(self, entry: RemediationEntry) -> RemediationEntry:
        self._replace(entry)
        return entry

    def get(self, entry_id: UUID, *, workspace_id: UUID) -> RemediationEntry | None:
        for e in self.saved:
            if e.id == entry_id and e.workspace_id == workspace_id and not e.is_deleted:
                return e
        return None

    def find_by_finding_task(self, *, workspace_id: UUID, finding_task_id: str) -> RemediationEntry | None:
        for e in self.saved:
            if e.workspace_id == workspace_id and e.finding_task_id == finding_task_id and not e.is_deleted:
                return e
        return None

    def list_for_workspace(self, workspace_id: UUID, *, limit: int = 50) -> list[RemediationEntry]:
        return [e for e in self.saved if e.workspace_id == workspace_id and not e.is_deleted][:limit]

    def find_active_priors(
        self,
        *,
        workspace_id: UUID,
        finding_kind: str,
        exclude_entry_id: UUID,
        limit: int = 50,
    ) -> list[RemediationEntry]:
        return [
            e
            for e in self.saved
            if e.workspace_id == workspace_id
            and e.finding_kind == finding_kind
            and e.id != exclude_entry_id
            and not e.is_deleted
        ][:limit]

    def filter_active_entry_ids(self, *, workspace_id, entry_ids: list[str]) -> set[str]:
        wanted = {str(e) for e in (entry_ids or []) if e}
        return {
            str(e.id)
            for e in self.saved
            if str(e.id) in wanted and str(e.workspace_id) == str(workspace_id) and not e.is_deleted
        }

    def record_reuse_success(self, *, entry_id: UUID, workspace_id: UUID) -> RemediationEntry | None:
        return self._bump(entry_id=entry_id, workspace_id=workspace_id, reuse=1, success=1, recurrence=0)

    def record_recurrence(self, *, entry_id: UUID, workspace_id: UUID) -> RemediationEntry | None:
        return self._bump(entry_id=entry_id, workspace_id=workspace_id, reuse=0, success=0, recurrence=1)

    def _bump(self, *, entry_id: UUID, workspace_id: UUID, reuse: int, success: int, recurrence: int):
        cur = self.get(entry_id, workspace_id=workspace_id)
        if cur is None:
            return None
        updated = replace(
            cur,
            reuse_count=cur.reuse_count + reuse,
            success_count=cur.success_count + success,
            recurrence_count=cur.recurrence_count + recurrence,
            score=RemediationRankingPolicy.derive_score(
                reuse_count=cur.reuse_count + reuse,
                success_count=cur.success_count + success,
                recurrence_count=cur.recurrence_count + recurrence,
            ),
        )
        self._replace(updated)
        return updated

    def revoke(
        self,
        *,
        entry_id: UUID,
        workspace_id: UUID,
        revoked_by: str,
        reason: str,
    ) -> RemediationEntry | None:
        for e in self.saved:
            if e.id == entry_id and e.workspace_id == workspace_id:
                revoked = e.revoked()
                self._replace(revoked)
                return revoked
        return None


class FakeSignOffGate(SignOffGatePort):
    def __init__(self, *, approved: bool) -> None:
        self._approved = approved

    def is_approved(self, *, artifact_type: str, artifact_id: str) -> bool:
        return self._approved


class FakeFindingFacts(FindingRemediationFactsPort):
    def __init__(self, facts: FindingRemediationFacts) -> None:
        self._facts = facts

    def get_facts(self, *, workspace_id: str, finding_task_id: str) -> FindingRemediationFacts:
        return self._facts


def make_facts(
    *,
    finding_task_id: str = "task-1",
    workspace_id: str = "ws-1",
    exists: bool = True,
    source_type: str = "ai.log_watch",
    finding_kind: str = "log_watch",
    finding_fingerprint: str = "fp-1",
    draft_pr_url: str | None = "https://github.com/acme/repo/pull/7",
    finding_resolved: bool = True,
    provenance_event_ref: str = "agent:triage@t1",
) -> FindingRemediationFacts:
    return FindingRemediationFacts(
        finding_task_id=finding_task_id,
        workspace_id=workspace_id,
        exists=exists,
        source_type=source_type,
        finding_kind=finding_kind,
        finding_fingerprint=finding_fingerprint,
        draft_pr_url=draft_pr_url,
        finding_resolved=finding_resolved,
        provenance_event_ref=provenance_event_ref,
    )
