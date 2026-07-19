import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace


def _create_user(email: str, username: str) -> CustomUser:
    user = CustomUser.objects.create_user(
        email=email,
        username=username,
        password="pass1234",
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def _create_workspace(owner: CustomUser) -> Workspace:
    return Workspace.objects.create(
        workspace_name="Activation Workspace",
        workspace_owner=owner,
        status="active",
    )



@pytest.mark.django_db
def test_team_activate_updates_active_context():
    owner = _create_user("owner-activate@example.com", "owner-activate")
    workspace = _create_workspace(owner)
    team = Team.objects.create(workspace=workspace, title="Active Team", created_by=owner)
    team.members.add(owner)

    profile = owner.profile
    profile.active_workspace_id = None
    profile.active_team_id = 0
    profile.save(update_fields=["active_workspace_id", "active_team_id"])

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("team:team-activate"),
        {"team_id": team.id},
        format="json",
    )

    assert response.status_code == 200
    owner.profile.refresh_from_db()
    assert owner.profile.active_team_id == team.id
    assert owner.profile.active_workspace_id == workspace.id


@pytest.mark.django_db
def test_workspace_activate_picks_first_accessible_team():
    """POST /team/workspace/activate/ resolves a team server-side and
    persists active_team_id + active_workspace_id in one round-trip.

    Mirrors what the frontend toggle calls now that the two-step
    getTeamsBySeed + activateTeam dance has collapsed into a single
    endpoint."""
    owner = _create_user("owner-ws-activate@example.com", "owner-ws-activate")
    workspace = _create_workspace(owner)
    team = Team.objects.create(
        workspace=workspace,
        title="Workspace Team",
        created_by=owner,
        plan=plan,
    )
    team.members.add(owner)

    profile = owner.profile
    profile.active_workspace_id = None
    profile.active_team_id = 0
    profile.save(update_fields=["active_workspace_id", "active_team_id"])

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("team:workspace-activate"),
        {"workspace_id": str(workspace.id)},
        format="json",
    )

    assert response.status_code == 200, response.content
    owner.profile.refresh_from_db()
    assert owner.profile.active_team_id == team.id
    assert owner.profile.active_workspace_id == workspace.id


@pytest.mark.django_db
def test_workspace_activate_returns_fresh_summary_for_new_workspace():
    """The activate response carries the post-switch me/summary payload so
    the frontend can apply role/persona/visible_sections atomically — no
    second GET /me/summary, no race window where the sidebar shows the
    previous workspace's sections while the summary fetch is in flight.

    Single source of truth for "what may this user see in the new
    workspace" lands in the same response that flipped the active
    workspace on the backend.
    """
    owner = _create_user("owner-summary@example.com", "owner-summary")
    workspace = _create_workspace(owner)
    team = Team.objects.create(
        workspace=workspace,
        title="Summary Team",
        created_by=owner,
        plan=plan,
    )
    team.members.add(owner)

    profile = owner.profile
    profile.active_workspace_id = None
    profile.active_team_id = 0
    profile.save(update_fields=["active_workspace_id", "active_team_id"])

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("team:workspace-activate"),
        {"workspace_id": str(workspace.id)},
        format="json",
    )

    assert response.status_code == 200, response.content
    body = response.json()
    summary = body.get("summary")
    assert summary, "activate response must include fresh me/summary"
    workspace_context = summary.get("workspace_context") or {}
    assert str(workspace_context.get("active_workspace_id")) == str(workspace.id), (
        "summary must reflect the just-activated workspace, not the previous one"
    )
    # The new workspace must appear in summary.workspaces with role +
    # visible_sections populated, so useWorkspaceVisibility renders the
    # right sidebar template on the very next frame.
    workspaces = summary.get("workspaces") or []
    match = next(
        (w for w in workspaces if str(w.get("id")) == str(workspace.id)),
        None,
    )
    assert match is not None, "activate summary must include the new workspace"
    assert match.get("role"), "new workspace must carry a resolved role"
    assert match.get("visible_sections") is not None


@pytest.mark.django_db
def test_team_activate_returns_fresh_summary_for_new_workspace():
    """Symmetric guarantee for the single-team activate endpoint — both
    paths must emit the same fresh-summary contract so the frontend
    handles them identically.
    """
    owner = _create_user("owner-team-summary@example.com", "owner-team-summary")
    workspace = _create_workspace(owner)
    team = Team.objects.create(
        workspace=workspace,
        title="Single Activate Team",
        created_by=owner,
        plan=plan,
    )
    team.members.add(owner)

    profile = owner.profile
    profile.active_workspace_id = None
    profile.active_team_id = 0
    profile.save(update_fields=["active_workspace_id", "active_team_id"])

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("team:team-activate"),
        {"team_id": team.id},
        format="json",
    )

    assert response.status_code == 200, response.content
    summary = response.json().get("summary")
    assert summary
    assert str(
        (summary.get("workspace_context") or {}).get("active_workspace_id")
    ) == str(workspace.id)


@pytest.mark.django_db
def test_workspace_activate_rejects_a_non_member():
    """A stranger with NO workspace membership (not owner, not a team
    member, no WorkspaceMembership row) is refused cleanly and their active
    context is left untouched — they can't activate a workspace they have
    no relationship with."""
    owner = _create_user("ws-owner@example.com", "ws-owner")
    stranger = _create_user("ws-stranger@example.com", "ws-stranger")
    workspace = _create_workspace(owner)
    team = Team.objects.create(
        workspace=workspace,
        title="Owner Team",
        created_by=owner,
        plan=plan,
    )
    team.members.add(owner)

    profile = stranger.profile
    profile.active_workspace_id = None
    profile.active_team_id = 0
    profile.save(update_fields=["active_workspace_id", "active_team_id"])

    client = APIClient()
    client.force_authenticate(user=stranger)
    response = client.post(
        reverse("team:workspace-activate"),
        {"workspace_id": str(workspace.id)},
        format="json",
    )

    # NotFoundError → 404 (the actor has no accessible relationship to this
    # workspace). The active pointer must remain unset.
    assert response.status_code == 404, response.content
    stranger.profile.refresh_from_db()
    assert stranger.profile.active_workspace_id is None


@pytest.mark.django_db
def test_workspace_activate_persists_pointer_for_teamless_member():
    """A workspace MEMBER who belongs to no internal team — e.g. a sponsor /
    viewer (ADR 0002) — can still activate the workspace. The endpoint
    persists active_workspace_id WITHOUT a team and clears active_team_id, so
    switching is team-independent (navigate() owns the view; this keeps the
    server-side active-workspace cache coherent for every persona)."""
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    owner = _create_user("ws-owner-tl@example.com", "ws-owner-tl")
    sponsor = _create_user("ws-sponsor-tl@example.com", "ws-sponsor-tl")
    workspace = _create_workspace(owner)
    # A team exists, but the sponsor is NOT a member of it.
    team = Team.objects.create(
        workspace=workspace,
        title="Owner Team",
        created_by=owner,
        plan=plan,
    )
    team.members.add(owner)

    # The sponsor is an ACTIVE workspace member (viewer role / sponsor
    # persona) but belongs to no team.
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=sponsor,
        role=WorkspaceMembership.Role.VIEWER,
        persona=WorkspaceMembership.Persona.SPONSOR,
        status=WorkspaceMembership.Status.ACTIVE,
    )

    # Seed a stale team pointer to prove the teamless activation clears it.
    profile = sponsor.profile
    profile.active_workspace_id = None
    profile.active_team_id = team.id
    profile.save(update_fields=["active_workspace_id", "active_team_id"])

    client = APIClient()
    client.force_authenticate(user=sponsor)
    response = client.post(
        reverse("team:workspace-activate"),
        {"workspace_id": str(workspace.id)},
        format="json",
    )

    assert response.status_code == 200, response.content
    body = response.json()
    # Teamless activation carries a null team payload.
    assert body["data"][0]["team"] is None
    sponsor.profile.refresh_from_db()
    assert sponsor.profile.active_workspace_id == workspace.id
    # active_team_id is a non-null IntegerField; 0 is the "no team" sentinel.
    assert sponsor.profile.active_team_id == 0
