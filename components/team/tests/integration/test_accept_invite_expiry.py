"""Invite-accept expiry handling.

Regression for a 500 caught by the QA E2E lifecycle suite (2026-07-02):
real invitations carry ``expires_at`` (+24h, naive under USE_TZ=False),
but the accept use case compared it against a tz-AWARE ``_utc_now()`` —
TypeError on every accept. The pre-existing tests never set
``expires_at``, so the short-circuit hid the bug.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from infrastructure.persistence.team.models import Invitation
from infrastructure.persistence.workspaces.models import WorkspaceMembership

ACCEPT_URL = "/membership/invitations/persona/accept/"


def _invite(workspace, email, *, expires_at):
    return Invitation.objects.create(
        workspace=workspace,
        email=email,
        token="e" * 64,
        persona="sponsor",
        role="sponsor",
        expires_at=expires_at,
    )


@pytest.mark.django_db
class TestAcceptInviteExpiry:
    def test_accept_with_live_naive_expiry_succeeds(self, api_client, workspace_factory):
        workspace = workspace_factory()
        # Naive datetime — exactly what the ORM stores/returns with USE_TZ=False.
        invitation = _invite(
            workspace, "fresh-invitee@example.com", expires_at=datetime.now() + timedelta(hours=24)
        )

        res = api_client.post(
            ACCEPT_URL,
            {
                "token": invitation.token,
                "password": "Str0ngEnough!",
                "first_name": "Fresh",
                "last_name": "Invitee",
            },
            format="json",
        )

        assert res.status_code in (200, 201), res.content
        assert WorkspaceMembership.objects.filter(
            workspace=workspace, user__email="fresh-invitee@example.com"
        ).exists()

    def test_accept_with_past_expiry_is_410(self, api_client, workspace_factory):
        workspace = workspace_factory()
        invitation = _invite(
            workspace, "late-invitee@example.com", expires_at=datetime.now() - timedelta(hours=1)
        )

        res = api_client.post(
            ACCEPT_URL,
            {
                "token": invitation.token,
                "password": "Str0ngEnough!",
                "first_name": "Late",
                "last_name": "Invitee",
            },
            format="json",
        )

        assert res.status_code == 410
        invitation.refresh_from_db()
        assert invitation.status == Invitation.EXPIRED
