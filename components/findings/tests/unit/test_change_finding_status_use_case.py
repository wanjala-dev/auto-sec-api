"""Unit tests for the finding lifecycle transition use case (no DB, in-memory store)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.findings.application.commands.change_finding_status_command import (
    ChangeFindingStatusCommand,
)
from components.findings.application.use_cases.change_finding_status_use_case import (
    ChangeFindingStatusUseCase,
)
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.domain.errors import (
    FindingNotFoundError,
    InvalidFindingActionError,
)
from components.shared_kernel.domain.security import FindingStatus, Severity

pytestmark = [pytest.mark.unit]

NOW = datetime(2026, 8, 3, tzinfo=UTC)


class _FakeStore:
    """Minimal in-memory FindingStorePort double — only the two methods the use case uses."""

    def __init__(self, finding: FindingEntity | None = None):
        self._by_id: dict = {}
        if finding is not None:
            self._by_id[(finding.workspace_id, finding.id)] = finding
        self.upserts: list[FindingEntity] = []

    def find_by_id(self, workspace_id, finding_id):
        return self._by_id.get((workspace_id, finding_id))

    def upsert(self, finding: FindingEntity) -> None:
        self.upserts.append(finding)
        self._by_id[(finding.workspace_id, finding.id)] = finding


def _finding(*, status=FindingStatus.OPEN) -> FindingEntity:
    return FindingEntity(
        id=uuid4(),
        workspace_id=uuid4(),
        source="cloud_posture.trivy",
        fingerprint="CVE-2024-1234",
        asset_urn="arn:aws:ec2:::i-1",
        severity=Severity.HIGH,
        status=status,
        title="CVE-2024-1234 in libfoo",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def _cmd(finding: FindingEntity, action: str) -> ChangeFindingStatusCommand:
    return ChangeFindingStatusCommand(
        workspace_id=finding.workspace_id,
        finding_id=finding.id,
        action=action,
        at=NOW,
        actor_id="actor-1",
    )


class TestChangeFindingStatusUseCase:
    def test_resolve_marks_resolved_and_stamps_resolved_at(self):
        f = _finding()
        store = _FakeStore(f)
        result = ChangeFindingStatusUseCase(store=store).execute(_cmd(f, "resolve"))

        assert result.changed is True
        assert result.status == "resolved"
        assert store.upserts[0].status is FindingStatus.RESOLVED
        assert store.upserts[0].resolved_at == NOW

    def test_suppress_dismisses_without_hard_delete(self):
        f = _finding()
        store = _FakeStore(f)
        result = ChangeFindingStatusUseCase(store=store).execute(_cmd(f, "suppress"))

        assert result.status == "suppressed"
        assert store.upserts[0].status is FindingStatus.SUPPRESSED
        # The record is retained (upserted, not deleted) — auditable + re-observable.
        assert len(store.upserts) == 1

    def test_reopen_returns_terminal_finding_to_open(self):
        f = _finding(status=FindingStatus.RESOLVED)
        store = _FakeStore(f)
        result = ChangeFindingStatusUseCase(store=store).execute(_cmd(f, "reopen"))

        assert result.status == "open"
        assert store.upserts[0].status is FindingStatus.OPEN
        assert store.upserts[0].resolved_at is None

    def test_idempotent_noop_when_already_in_target_state(self):
        f = _finding(status=FindingStatus.RESOLVED)
        store = _FakeStore(f)
        result = ChangeFindingStatusUseCase(store=store).execute(_cmd(f, "resolve"))

        assert result.changed is False
        assert store.upserts == []  # nothing written

    def test_missing_finding_raises_not_found(self):
        f = _finding()
        store = _FakeStore()  # empty
        with pytest.raises(FindingNotFoundError):
            ChangeFindingStatusUseCase(store=store).execute(_cmd(f, "resolve"))

    def test_unknown_action_raises_invalid_action(self):
        f = _finding()
        store = _FakeStore(f)
        with pytest.raises(InvalidFindingActionError):
            ChangeFindingStatusUseCase(store=store).execute(_cmd(f, "nuke"))
