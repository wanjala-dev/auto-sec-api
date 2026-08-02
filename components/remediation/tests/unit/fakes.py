"""In-memory fakes for the remediation ports — no DB, no framework.

Let the gate be exercised as pure orchestration: the store records what it was
asked to save (so a test can assert the gate wrote nothing on refusal), and the
two read-ports return scripted facts.
"""

from __future__ import annotations

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


class FakeStore(RemediationEntryStorePort):
    def __init__(self) -> None:
        self.saved: list[RemediationEntry] = []

    def save(self, entry: RemediationEntry) -> RemediationEntry:
        self.saved.append(entry)
        return entry

    def get(self, entry_id: UUID, *, workspace_id: UUID) -> RemediationEntry | None:
        for e in self.saved:
            if e.id == entry_id and e.workspace_id == workspace_id:
                return e
        return None

    def find_by_finding_task(self, *, workspace_id: UUID, finding_task_id: str) -> RemediationEntry | None:
        for e in self.saved:
            if e.workspace_id == workspace_id and e.finding_task_id == finding_task_id and not e.is_deleted:
                return e
        return None

    def list_for_workspace(self, workspace_id: UUID, *, limit: int = 50) -> list[RemediationEntry]:
        return [e for e in self.saved if e.workspace_id == workspace_id and not e.is_deleted][:limit]


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
