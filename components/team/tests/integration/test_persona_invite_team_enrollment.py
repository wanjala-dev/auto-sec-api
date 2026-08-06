"""Persona-invite TEAM ENROLLMENT — the #60 regression suite.

The original inline enrollment on accept imported a renamed class
(``TeamMembershipRepository`` → ``OrmTeamMembershipRepository``); the resulting
ImportError was swallowed by a bare ``except Exception: pass``, so every
team-attached persona invite (contributor / volunteer) silently skipped putting
the acceptor INTO the invited team — for months. The root fix routes enrollment
through the team-owned ``InviteTeamEnrollmentPort``; these tests drive the REAL
endpoints (create → accept) and assert the enrollment side effects that were
silently missing:

* the acceptor is in ``team.members`` (the M2M the board/HUD read),
* an ACTIVE ``TeamMembership`` row exists,
* the profile's active team context points at the invited team,
* ``is_contributor`` obeys the persona rule (contributor → True; volunteer → False),
* a team deleted between invite and accept degrades to a logged no-op — the
  accept (and the WorkspaceMembership write) still succeeds.
"""

from __future__ import annotations

import pytest

from infrastructure.persistence.team.models import Team, TeamMembership
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import WorkspaceMembership

INVITE_URL = "/membership/invitations/persona/"
ACCEPT_URL = "/membership/invitations/persona/accept/"

_PASSWORD = "InviteAccept2026!"


@pytest.fixture
def org(workspace_factory, team_factory):
    ws = workspace_factory()
    owner = ws.workspace_owner
    team = team_factory(workspace=ws, created_by=owner, members=[owner])
    return ws, owner, team


def _invite(api_client, owner, ws, team, *, persona, email):
    api_client.force_authenticate(owner)
    resp = api_client.post(
        INVITE_URL,
        {
            "workspace_id": str(ws.id),
            "email": email,
            "persona": persona,
            "team_id": str(team.id) if team is not None else None,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    api_client.force_authenticate()  # accept is unauthenticated (magic link)
    return resp.data["token"]


def _accept(api_client, token):
    return api_client.post(
        ACCEPT_URL,
        {"token": token, "password": _PASSWORD, "first_name": "New", "last_name": "Member"},
        format="json",
    )


@pytest.mark.integration
@pytest.mark.django_db
class TestPersonaInviteTeamEnrollment:
    def test_contributor_accept_enrolls_into_the_invited_team(self, api_client, org):
        ws, owner, team = org
        token = _invite(api_client, owner, ws, team, persona="contributor", email="analyst@acme-soc.example")

        resp = _accept(api_client, token)

        assert resp.status_code == 200, resp.data
        user = CustomUser.objects.get(email="analyst@acme-soc.example")

        # The workspace membership row (already working before the fix).
        membership = WorkspaceMembership.objects.get(workspace=ws, user=user)
        assert membership.status == WorkspaceMembership.Status.ACTIVE
        assert membership.persona == "contributor"

        # The #60 side effects — all silently missing before the fix:
        assert team.members.filter(id=user.id).exists(), "acceptor never landed in team.members (#60)"
        team_row = TeamMembership.objects.get(team=team, user=user)
        assert team_row.status == TeamMembership.Status.ACTIVE
        profile = UserProfile.objects.get(user=user)
        assert str(profile.active_workspace_id) == str(ws.id)
        assert str(profile.active_team_id) == str(team.id)
        # Contributor persona flips the global flag (the accept flow's own rule).
        assert user.is_contributor is True

    def test_volunteer_accept_enrolls_without_marking_contributor(self, api_client, org):
        ws, owner, team = org
        token = _invite(api_client, owner, ws, team, persona="volunteer", email="volunteer@acme-soc.example")

        resp = _accept(api_client, token)

        assert resp.status_code == 200, resp.data
        user = CustomUser.objects.get(email="volunteer@acme-soc.example")
        assert team.members.filter(id=user.id).exists()
        assert TeamMembership.objects.filter(team=team, user=user, status=TeamMembership.Status.ACTIVE).exists()
        # The persona rule holds: only a CONTRIBUTOR invite may set the global flag.
        assert user.is_contributor is False

    def test_team_detached_persona_creates_no_team_membership(self, api_client, org):
        ws, owner, team = org
        token = _invite(api_client, owner, ws, None, persona="auditor", email="auditor@acme-soc.example")

        resp = _accept(api_client, token)

        assert resp.status_code == 200, resp.data
        user = CustomUser.objects.get(email="auditor@acme-soc.example")
        assert WorkspaceMembership.objects.filter(workspace=ws, user=user).exists()
        assert not TeamMembership.objects.filter(user=user).exists()
        assert not team.members.filter(id=user.id).exists()

    def test_team_deleted_after_invite_kills_the_link_cleanly(self, api_client, org):
        """``Invitation.team`` is ``on_delete=CASCADE``: deleting the team deletes the
        pending invitation, so the magic link 404s and NOTHING is half-written (no
        user activation, no membership). Pins the cascade contract; the adapter's
        missing-row guard stays as defense-in-depth for non-cascade races."""
        ws, owner, team = org
        token = _invite(api_client, owner, ws, team, persona="contributor", email="late@acme-soc.example")
        Team.objects.filter(id=team.id).delete()

        resp = _accept(api_client, token)

        assert resp.status_code == 404, resp.data
        # The invite-time placeholder user may exist, but no membership was written.
        assert not WorkspaceMembership.objects.filter(workspace=ws, user__email="late@acme-soc.example").exists()
        assert not TeamMembership.objects.filter(user__email="late@acme-soc.example").exists()
