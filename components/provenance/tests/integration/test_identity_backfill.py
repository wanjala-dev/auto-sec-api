"""Integration tests for the membership -> AccessGrant backfill."""

from __future__ import annotations

import pytest

from components.provenance.infrastructure.services.identity_backfill_service import (
    backfill_from_memberships,
)
from infrastructure.persistence.provenance.models import AccessGrant, ProvenanceActor
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_membership_projects_role_grant_on_workspace_resource(workspace_factory, user_factory):
    ws = workspace_factory()
    user = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="admin")

    counts = backfill_from_memberships(workspace_id=ws.id)

    assert counts["grants"] >= 1
    actor = ProvenanceActor.objects.get(workspace=ws, external_ref=str(user.id))
    grant = AccessGrant.objects.get(workspace=ws, actor=actor)
    assert grant.source == "membership:admin"
    assert set(grant.permissions) == {"read", "write", "execute", "admin"}
    assert grant.resource.resource_type == "workspace"
    assert grant.scope == "workspace"


def test_viewer_role_maps_to_read_only(workspace_factory, user_factory):
    ws = workspace_factory()
    user = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=user, role="viewer")

    backfill_from_memberships(workspace_id=ws.id)

    actor = ProvenanceActor.objects.get(workspace=ws, external_ref=str(user.id))
    grant = AccessGrant.objects.get(workspace=ws, actor=actor)
    assert list(grant.permissions) == ["read"]


def test_membership_backfill_is_idempotent(workspace_factory, user_factory):
    ws = workspace_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=user_factory(), role="member")

    first = backfill_from_memberships(workspace_id=ws.id)
    second = backfill_from_memberships(workspace_id=ws.id)

    assert first["grants"] >= 1
    assert second["actors"] == 0
    assert second["resources"] == 0
    assert second["grants"] == 0
