"""Integration — suppressing a finding auto-archives its board card (Henry's
2026-08-09 ruling), reversibly, through the recycle bin.

Covers the whole loop, piecewise (the event hop between the two is Celery):

* ``ChangeFindingStatusUseCase`` emits ``FindingResolved(reason="suppressed")``
  on suppress (and ``"resolved"`` on resolve; nothing on reopen / no-ops);
* ``handle_finding_resolved_board`` archives the suppressed finding's card —
  recycle-bin tombstone + provenance event + reason-stamped card comment —
  and ignores every other reason token;
* the existing RECYCLE BIN restore flow still works on an auto-archived card;
* the board read's per-lane totals (``tasks_total``) drop accordingly;
* the ``archive_suppressed_finding_cards`` backfill command archives every
  already-suppressed finding's card, idempotently, and leaves open findings'
  cards alone.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.management import call_command
from django.urls import reverse

from components.agents.application.handlers.finding_resolved_board_handler import (
    handle_finding_resolved_board,
)
from components.findings.application.commands.change_finding_status_command import (
    ChangeFindingStatusCommand,
)
from components.findings.application.providers.finding_provider import FindingProvider
from components.findings.application.use_cases.change_finding_status_use_case import (
    ChangeFindingStatusUseCase,
)
from components.recycle_bin.application.commands.restore_command import RestoreCommand
from components.recycle_bin.application.providers.recycle_bin_provider import (
    get_recycle_bin_service,
)
from components.shared_kernel.domain.events import FindingResolved
from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.project.models import Column, Task, TaskComment
from infrastructure.persistence.users.models import UserProfile

pytestmark = pytest.mark.django_db


class RecordingPublisher:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


def _finding(workspace, *, fingerprint="fp-1", status="open", status_reason=""):
    now = datetime.now(UTC)
    return Finding.objects.create(
        workspace=workspace,
        source="cloud_posture.prowler",
        fingerprint=fingerprint,
        asset_urn="urn:aws:s3:bucket/demo",
        severity="high",
        status=status,
        status_reason=status_reason,
        title=f"Finding {fingerprint}",
        first_seen_at=now,
        last_seen_at=now,
    )


def _card(workspace, team, column, user, finding, *, title=None):
    return Task.objects.create(
        workspace=workspace,
        team=team,
        column=column,
        title=title or f"Card for {finding.fingerprint}",
        status=Task.TODO,
        created_by=user,
        source_type="ai.detection",
        metadata={"payload": {"finding_id": str(finding.id), "lookup_key": finding.fingerprint}},
    )


@pytest.fixture
def board(workspace_factory, team_factory, user_factory):
    owner = user_factory()
    UserProfile.objects.get_or_create(user=owner)
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(workspace=workspace, team=team, title="Suggested", created_by=owner)
    return owner, workspace, team, column


def _suppressed_event(workspace, finding):
    return FindingResolved(
        workspace_id=workspace.id,
        finding_id=finding.id,
        fingerprint=finding.fingerprint,
        reason="suppressed",
    )


class TestChangeStatusEmitsFindingResolved:
    def _use_case(self, publisher):
        return ChangeFindingStatusUseCase(
            store=FindingProvider.build_finding_store(),
            event_publisher=publisher,
        )

    def test_suppress_publishes_suppressed_reason(self, board):
        _owner, workspace, _team, _column = board
        finding = _finding(workspace)
        publisher = RecordingPublisher()

        self._use_case(publisher).execute(
            ChangeFindingStatusCommand(
                workspace_id=workspace.id,
                finding_id=finding.id,
                action="suppress",
                at=datetime.now(UTC),
                reason="demo noise",
            )
        )

        (event,) = publisher.published
        assert isinstance(event, FindingResolved)
        assert event.reason == "suppressed"
        assert event.finding_id == finding.id
        assert event.fingerprint == finding.fingerprint

    def test_resolve_publishes_resolved_reason(self, board):
        _owner, workspace, _team, _column = board
        finding = _finding(workspace, fingerprint="fp-r")
        publisher = RecordingPublisher()

        self._use_case(publisher).execute(
            ChangeFindingStatusCommand(
                workspace_id=workspace.id,
                finding_id=finding.id,
                action="resolve",
                at=datetime.now(UTC),
            )
        )

        (event,) = publisher.published
        assert event.reason == "resolved"

    def test_reopen_and_noop_publish_nothing(self, board):
        _owner, workspace, _team, _column = board
        finding = _finding(workspace, fingerprint="fp-n", status="suppressed", status_reason="x")
        publisher = RecordingPublisher()
        use_case = self._use_case(publisher)

        # Idempotent re-suppress with the SAME reason → no write, no event.
        use_case.execute(
            ChangeFindingStatusCommand(
                workspace_id=workspace.id,
                finding_id=finding.id,
                action="suppress",
                at=datetime.now(UTC),
                reason="x",
            )
        )
        assert publisher.published == []

        # Reopen is not a terminal transition → no FindingResolved.
        use_case.execute(
            ChangeFindingStatusCommand(
                workspace_id=workspace.id,
                finding_id=finding.id,
                action="reopen",
                at=datetime.now(UTC),
            )
        )
        assert publisher.published == []


class TestSuppressedCardAutoArchive:
    def test_handler_archives_card_with_provenance_and_comment(self, board):
        owner, workspace, team, column = board
        finding = _finding(workspace, status="suppressed", status_reason="accepted risk: demo noise")
        card = _card(workspace, team, column, owner, finding)

        handle_finding_resolved_board(_suppressed_event(workspace, finding))

        card.refresh_from_db()
        # Tombstoned, not deleted.
        assert card.status == Task.ARCHIVED
        assert Task.objects.filter(pk=card.pk).exists()

        # In the recycle bin (restorable), reason-stamped.
        entries = get_recycle_bin_service().list_bin(workspace_id=workspace.id, entity_type="task")
        matching = [e for e in entries if e.entity_id == str(card.pk)]
        assert len(matching) == 1

        # Provenance event on the card metadata.
        events = (card.metadata.get("provenance") or {}).get("events") or []
        assert any("finding suppressed (accepted risk: demo noise)" in e.get("action", "") for e in events)

        # Card comment naming the why (AI-actions-on-board principle).
        comments = list(TaskComment.objects.filter(task=card))
        assert len(comments) == 1
        assert "finding suppressed (accepted risk: demo noise)" in comments[0].comment

    def test_handler_ignores_other_reasons(self, board):
        owner, workspace, team, column = board
        finding = _finding(workspace, fingerprint="fp-res", status="resolved")
        card = _card(workspace, team, column, owner, finding)

        handle_finding_resolved_board(
            FindingResolved(
                workspace_id=workspace.id,
                finding_id=finding.id,
                fingerprint=finding.fingerprint,
                reason="resolved",
            )
        )
        handle_finding_resolved_board(
            FindingResolved(
                workspace_id=workspace.id,
                finding_id=finding.id,
                fingerprint=finding.fingerprint,
                reason="no_longer_observed",
            )
        )

        card.refresh_from_db()
        assert card.status == Task.TODO  # resolved/reconciler reasons never archive

    def test_handler_is_idempotent(self, board):
        owner, workspace, team, column = board
        finding = _finding(workspace, fingerprint="fp-i", status="suppressed")
        card = _card(workspace, team, column, owner, finding)

        handle_finding_resolved_board(_suppressed_event(workspace, finding))
        handle_finding_resolved_board(_suppressed_event(workspace, finding))

        card.refresh_from_db()
        assert card.status == Task.ARCHIVED
        entries = get_recycle_bin_service().list_bin(workspace_id=workspace.id, entity_type="task")
        assert len([e for e in entries if e.entity_id == str(card.pk)]) == 1
        assert TaskComment.objects.filter(task=card).count() == 1

    def test_restore_from_recycle_bin_still_works(self, board):
        owner, workspace, team, column = board
        finding = _finding(workspace, fingerprint="fp-restore", status="suppressed")
        card = _card(workspace, team, column, owner, finding)

        handle_finding_resolved_board(_suppressed_event(workspace, finding))

        service = get_recycle_bin_service()
        entries = service.list_bin(workspace_id=workspace.id, entity_type="task")
        (entry,) = [e for e in entries if e.entity_id == str(card.pk)]
        service.restore(RestoreCommand(entry_id=entry.id, restored_by=owner.id))

        card.refresh_from_db()
        assert card.status == Task.TODO  # pre-trash status returns

    def test_board_lane_total_drops(self, api_client, board):
        owner, workspace, team, column = board
        finding = _finding(workspace, fingerprint="fp-lane", status="suppressed")
        _card(workspace, team, column, owner, finding)
        keeper = _finding(workspace, fingerprint="fp-keep", status="open")
        _card(workspace, team, column, owner, keeper)

        api_client.force_authenticate(owner)
        url = reverse(
            "project:columns-by-team-workspace",
            kwargs={"team_id": team.id, "workspace_id": workspace.id},
        )
        before = api_client.get(url).data["data"][0]
        assert before["tasks_total"] == 2

        handle_finding_resolved_board(_suppressed_event(workspace, finding))

        after = api_client.get(url).data["data"][0]
        assert after["tasks_total"] == 1
        assert [t["title"] for t in after["tasks"]] == ["Card for fp-keep"]


class TestBackfillCommand:
    def test_backfill_archives_suppressed_only_and_is_idempotent(self, board, capsys):
        owner, workspace, team, column = board
        suppressed = [
            _finding(workspace, fingerprint=f"fp-s{i}", status="suppressed", status_reason="demo noise")
            for i in range(3)
        ]
        for f in suppressed:
            _card(workspace, team, column, owner, f)
        open_finding = _finding(workspace, fingerprint="fp-open", status="open")
        open_card = _card(workspace, team, column, owner, open_finding)

        call_command("archive_suppressed_finding_cards", workspace=str(workspace.id))

        archived = Task.objects.filter(workspace=workspace, status=Task.ARCHIVED)
        assert archived.count() == 3
        open_card.refresh_from_db()
        assert open_card.status == Task.TODO

        # Reason-stamped comments on every archived card.
        assert TaskComment.objects.filter(task__in=archived).count() == 3

        # Idempotent: the second run archives nothing new, doubles no comments.
        call_command("archive_suppressed_finding_cards", workspace=str(workspace.id))
        assert Task.objects.filter(workspace=workspace, status=Task.ARCHIVED).count() == 3
        assert TaskComment.objects.filter(task__in=archived).count() == 3

    def test_backfill_dry_run_archives_nothing(self, board):
        owner, workspace, team, column = board
        finding = _finding(workspace, fingerprint="fp-dry", status="suppressed")
        card = _card(workspace, team, column, owner, finding)

        call_command("archive_suppressed_finding_cards", workspace=str(workspace.id), dry_run=True)

        card.refresh_from_db()
        assert card.status == Task.TODO
        assert not get_recycle_bin_service().list_bin(workspace_id=workspace.id, entity_type="task")
