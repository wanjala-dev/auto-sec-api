from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.membership.application.use_cases.process_invitation_batch_use_case import (
    ProcessInvitationBatchUseCase,
)


def test_process_team_invitation_batch_processes_existing_and_new_targets():
    prepare_use_case = SimpleNamespace(
        execute=Mock(
            return_value=SimpleNamespace(
                workspace=SimpleNamespace(id="workspace-1"),
                team=SimpleNamespace(title="Alpha"),
                existing_users=[SimpleNamespace(id="user-1", email="existing@example.com")],
                new_emails=["new@example.com"],
                missing_user_ids=["missing-1"],
            )
        )
    )
    issue_use_case = SimpleNamespace(
        execute=Mock(
            side_effect=[
                SimpleNamespace(status="added", invitation="inv-1"),
                SimpleNamespace(status="added", invitation="inv-2"),
            ]
        )
    )
    register_use_case = SimpleNamespace(
        execute=Mock(return_value=SimpleNamespace(id="user-2", email="new@example.com"))
    )
    notification_use_case = SimpleNamespace(
        handle_invitation_issued=Mock(),
    )
    actor = SimpleNamespace(id="actor-1", is_authenticated=True)
    handler = ProcessInvitationBatchUseCase(
        prepare_use_case=prepare_use_case,
        issue_use_case=issue_use_case,
        register_use_case=register_use_case,
        notification_use_case=notification_use_case,
    )

    result = handler.execute(
        actor=actor,
        workspace_id="workspace-1",
        team_id=7,
        emails=["existing@example.com", "new@example.com"],
        user_ids=["user-1"],
        request="request",
    )

    assert result.message == "Invites processed."
    assert result.results == {
        "added": [
            {"user_id": "user-1", "email": "existing@example.com"},
            {"user_id": "user-2", "email": "new@example.com"},
        ],
        "skipped": [],
        "missing": [{"user_id": "missing-1"}],
    }
    register_use_case.execute.assert_called_once_with(
        email="new@example.com",
        name="new",
        request="request",
        team_name="Alpha",
        workspace_id="workspace-1",
    )
    assert notification_use_case.handle_invitation_issued.call_count == 2


def test_process_team_invitation_batch_skips_missing_and_duplicate_targets():
    prepare_use_case = SimpleNamespace(
        execute=Mock(
            return_value=SimpleNamespace(
                workspace=SimpleNamespace(id="workspace-1"),
                team=SimpleNamespace(title="Alpha"),
                existing_users=[SimpleNamespace(id="user-1", email="")],
                new_emails=["new@example.com"],
                missing_user_ids=[],
            )
        )
    )
    issue_use_case = SimpleNamespace(
        execute=Mock(
            return_value=SimpleNamespace(
                status="skipped",
                reason="already_invited",
            )
        )
    )
    register_use_case = SimpleNamespace(
        execute=Mock(return_value=SimpleNamespace(id="user-2", email="new@example.com"))
    )
    notification_use_case = SimpleNamespace(
        handle_invitation_issued=Mock(),
    )
    actor = SimpleNamespace(id="actor-1", is_authenticated=True)
    handler = ProcessInvitationBatchUseCase(
        prepare_use_case=prepare_use_case,
        issue_use_case=issue_use_case,
        register_use_case=register_use_case,
        notification_use_case=notification_use_case,
    )

    result = handler.execute(
        actor=actor,
        workspace_id="workspace-1",
        team_id=None,
        emails=["new@example.com"],
        user_ids=[],
        request=None,
    )

    assert result.results == {
        "added": [],
        "skipped": [
            {"user_id": "user-1", "reason": "missing_email"},
            {"user_id": "user-2", "email": "new@example.com", "reason": "already_invited"},
        ],
        "missing": [],
    }
    notification_use_case.handle_invitation_issued.assert_not_called()
