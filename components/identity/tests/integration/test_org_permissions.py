import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from components.workspace.api.permissions import IsTeamEditor, IsTeamLead, IsWorkspaceAdmin
from infrastructure.persistence.team.models import Team, TeamMembership
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


@pytest.fixture
def api_factory():
    return APIRequestFactory()


def create_user(email: str, username: str) -> CustomUser:
    user = CustomUser.objects.create_user(
        email=email,
        username=username,
        password="password123",
    )
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user


@pytest.mark.django_db
def test_workspace_admin_permission_allows_owner(api_factory):
    owner = create_user("ownerperm@example.com", "ownerperm")
    workspace = Workspace.objects.create(workspace_name="Perm Workspace", workspace_owner=owner, status="active")
    request = Request(api_factory.post("/", {"workspace": str(workspace.id)}, format="json"))
    request.user = owner
    perm = IsWorkspaceAdmin()
    assert perm.has_permission(request, view=type("View", (), {"kwargs": {}})())


@pytest.mark.django_db
def test_workspace_admin_permission_allows_admin_membership(api_factory):
    owner = create_user("owner2@example.com", "owner2")
    admin = create_user("admin@example.com", "adminuser")
    workspace = Workspace.objects.create(workspace_name="Admin Workspace", workspace_owner=owner, status="active")
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=admin,
        role=WorkspaceMembership.Role.ADMIN,
        status=WorkspaceMembership.Status.ACTIVE,
    )
    request = Request(api_factory.post("/", {"workspace": str(workspace.id)}, format="json"))
    request.user = admin
    perm = IsWorkspaceAdmin()
    assert perm.has_permission(request, view=type("View", (), {"kwargs": {}})())


@pytest.mark.django_db
def test_workspace_admin_permission_denies_non_member(api_factory):
    owner = create_user("owner3@example.com", "owner3")
    outsider = create_user("outsider@example.com", "outsider")
    workspace = Workspace.objects.create(workspace_name="Out Workspace", workspace_owner=owner, status="active")
    request = Request(api_factory.post("/", {"workspace": str(workspace.id)}, format="json"))
    request.user = outsider
    perm = IsWorkspaceAdmin()
    assert not perm.has_permission(request, view=type("View", (), {"kwargs": {}})())


@pytest.mark.django_db
def test_team_lead_permission_allows_lead(api_factory):
    owner = create_user("leadowner@example.com", "leadowner")
    lead = create_user("lead@example.com", "leaduser")
    workspace = Workspace.objects.create(workspace_name="Lead Workspace", workspace_owner=owner, status="active")
    team = Team.objects.create(title="Lead Team", workspace=workspace, created_by=owner)
    TeamMembership.objects.create(
        team=team,
        user=lead,
        role=TeamMembership.Role.LEAD,
        status=TeamMembership.Status.ACTIVE,
    )
    request = Request(api_factory.post("/", {"team": team.id}, format="json"))
    request.user = lead
    perm = IsTeamLead()
    assert perm.has_permission(request, view=type("View", (), {"kwargs": {}})())


@pytest.mark.django_db
def test_team_lead_permission_denies_editor(api_factory):
    owner = create_user("leadowner2@example.com", "leadowner2")
    editor = create_user("editor@example.com", "editoruser")
    workspace = Workspace.objects.create(workspace_name="Editor Workspace", workspace_owner=owner, status="active")
    team = Team.objects.create(title="Editor Team", workspace=workspace, created_by=owner)
    TeamMembership.objects.create(
        team=team,
        user=editor,
        role=TeamMembership.Role.EDITOR,
        status=TeamMembership.Status.ACTIVE,
    )
    request = Request(api_factory.post("/", {"team_id": team.id}, format="json"))
    request.user = editor
    perm = IsTeamLead()
    assert not perm.has_permission(request, view=type("View", (), {"kwargs": {}})())


@pytest.mark.django_db
def test_team_editor_permission_allows_editor(api_factory):
    owner = create_user("owner-editor@example.com", "owner-editor")
    editor = create_user("editor2@example.com", "editor2")
    workspace = Workspace.objects.create(workspace_name="Team Workspace", workspace_owner=owner, status="active")
    team = Team.objects.create(title="Team", workspace=workspace, created_by=owner)
    TeamMembership.objects.create(
        team=team,
        user=editor,
        role=TeamMembership.Role.EDITOR,
        status=TeamMembership.Status.ACTIVE,
    )
    request = Request(api_factory.post("/", {"team": team.id}, format="json"))
    request.user = editor
    perm = IsTeamEditor()
    assert perm.has_permission(request, view=type("View", (), {"kwargs": {}})())
