from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

from components.team.application.queries.team_membership_query import (
    TeamMembershipQueryService,
)


def test_list_user_teams_requires_authenticated_actor():
    service = TeamMembershipQueryService(team_membership_queries=Mock())

    try:
        service.list_user_teams(actor_id=None)
    except PermissionError as exc:
        assert str(exc) == "Authentication required."
    else:
        raise AssertionError("Expected PermissionError for missing actor.")


def test_list_user_teams_rejects_other_user_without_staff_access():
    service = TeamMembershipQueryService(team_membership_queries=Mock())

    try:
        service.list_user_teams(actor_id="user-1", user_id="user-2")
    except PermissionError as exc:
        assert str(exc) == "You do not have permission to access this resource."
    else:
        raise AssertionError("Expected PermissionError for cross-user access.")


def test_list_user_teams_delegates_to_queries():
    queries = SimpleNamespace(
        list_user_teams=Mock(return_value=["team"]),
    )
    service = TeamMembershipQueryService(team_membership_queries=queries)

    teams = service.list_user_teams(
        actor_id="user-1",
        user_id="user-1",
    )

    assert teams == ["team"]
    queries.list_user_teams.assert_called_once_with(
        actor_id="user-1",
        user_id="user-1",
    )


def test_list_workspace_team_members_requires_workspace_id():
    service = TeamMembershipQueryService(team_membership_queries=Mock())

    try:
        service.list_workspace_team_members(workspace_id=None, actor_id="user-1")
    except ValueError as exc:
        assert str(exc) == "workspace_id is required."
    else:
        raise AssertionError("Expected ValueError when workspace_id is missing.")


def test_get_team_detail_parses_team_id_before_query():
    queries = SimpleNamespace(
        get_team_detail=Mock(return_value="team-object"),
    )
    service = TeamMembershipQueryService(team_membership_queries=queries)

    team = service.get_team_detail(
        team_id="12",
        actor_id="user-1",
    )

    assert team == "team-object"
    queries.get_team_detail.assert_called_once_with(
        team_id=12,
        actor_id="user-1",
        is_staff=False,
        is_superuser=False,
    )


def test_list_workspace_teams_parses_uuid_before_query():
    workspace_id = uuid.uuid4()
    queries = SimpleNamespace(
        list_workspace_teams=Mock(return_value=(["team"], True)),
    )
    service = TeamMembershipQueryService(team_membership_queries=queries)

    teams, can_view_full = service.list_workspace_teams(
        workspace_id=str(workspace_id),
        actor_id="user-1",
        team_name="Alpha",
    )

    assert teams == ["team"]
    assert can_view_full is True
    queries.list_workspace_teams.assert_called_once_with(
        workspace_id=workspace_id,
        actor_id="user-1",
        team_name="Alpha",
        is_staff=False,
        is_superuser=False,
    )


def test_list_workspace_team_members_parses_uuid_before_query():
    workspace_id = uuid.uuid4()
    queries = SimpleNamespace(
        list_workspace_team_members=Mock(return_value=(["user"], {1: []})),
    )
    service = TeamMembershipQueryService(team_membership_queries=queries)

    members, team_lookup = service.list_workspace_team_members(
        workspace_id=str(workspace_id),
        actor_id="user-1",
        is_staff=True,
    )

    assert members == ["user"]
    assert team_lookup == {1: []}
    queries.list_workspace_team_members.assert_called_once_with(
        workspace_id=workspace_id,
        actor_id="user-1",
        is_staff=True,
        is_superuser=False,
    )


def test_list_workspace_pending_invitations_parses_uuid_before_query():
    workspace_id = uuid.uuid4()
    queries = SimpleNamespace(
        list_workspace_pending_invitations=Mock(return_value=[{"email": "invitee@example.com"}]),
    )
    service = TeamMembershipQueryService(team_membership_queries=queries)

    payload = service.list_workspace_pending_invitations(
        workspace_id=str(workspace_id),
        actor_id="user-1",
    )

    assert payload == [{"email": "invitee@example.com"}]
    queries.list_workspace_pending_invitations.assert_called_once_with(
        workspace_id=workspace_id,
        actor_id="user-1",
        is_staff=False,
        is_superuser=False,
    )
