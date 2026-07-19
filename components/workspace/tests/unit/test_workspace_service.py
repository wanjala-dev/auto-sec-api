from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.workspace.application.service import WorkspaceService


def test_get_or_create_default_team_returns_none_without_workspace():
    service = WorkspaceService(team_membership_store=Mock())

    assert service.get_or_create_default_team(None) is None


def test_enroll_user_in_team_skips_missing_user_or_team():
    store = SimpleNamespace(enroll_user_in_team=Mock())
    service = WorkspaceService(team_membership_store=store)

    service.enroll_user_in_team(None, "workspace", "team")
    service.enroll_user_in_team("user", "workspace", None)

    store.enroll_user_in_team.assert_not_called()


def test_enroll_user_in_team_delegates_to_store():
    store = SimpleNamespace(enroll_user_in_team=Mock())
    service = WorkspaceService(team_membership_store=store)

    service.enroll_user_in_team(
        "user",
        "workspace",
        "team",
        mark_contributor=False,
        update_active_context=True,
    )

    store.enroll_user_in_team.assert_called_once_with(
        "user",
        "workspace",
        "team",
        mark_contributor=False,
        update_active_context=True,
    )


def test_ensure_contributor_membership_requires_user_and_workspace():
    store = SimpleNamespace(ensure_contributor_membership=Mock())
    service = WorkspaceService(team_membership_store=store)

    assert service.ensure_contributor_membership(None, "workspace") is None
    assert service.ensure_contributor_membership("user", None) is None
    store.ensure_contributor_membership.assert_not_called()
