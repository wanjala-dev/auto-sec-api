"""Integration tests for the audit read endpoints.

``GET /audit/workspace/entries/`` is the auditor read surface: every
tracked field change in one tenant, newest first, filterable and
paginated. ``GET /audit/entries/`` is the per-entity history. Both
share the ``IsAuditWorkspaceMember`` tenant gate (explicit
``workspace_id`` + active membership) so an operator can only read
their own workspace's trail.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from infrastructure.persistence.audit.models import EntityAuditLog
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

FEED_URL = "/audit/workspace/entries/"
ENTITY_URL = "/audit/entries/"


def _log(workspace, actor, field_name="workspace_name", previous="a", new="b"):
    """Write one audit row against the workspace entity itself."""
    ct = ContentType.objects.get_for_model(Workspace)
    return EntityAuditLog.objects.create(
        workspace=workspace,
        content_type=ct,
        object_id=str(workspace.id),
        field_name=field_name,
        previous_value=previous,
        new_value=new,
        actor=actor,
        reason="test edit",
    )


def _workspace_entity_type() -> str:
    ct = ContentType.objects.get_for_model(Workspace)
    return f"{ct.app_label}.{ct.model}"


@pytest.fixture
def seeded(workspace_factory):
    """Workspace with three audit rows against it."""
    workspace = workspace_factory()
    e1 = _log(workspace, workspace.workspace_owner, field_name="workspace_name")
    e2 = _log(workspace, workspace.workspace_owner, field_name="status", previous="active", new="suspended")
    e3 = _log(workspace, workspace.workspace_owner, field_name="workspace_name", previous="b", new="c")
    return workspace, [e1, e2, e3]


class TestTenantGate:
    def test_unauthenticated_returns_401(self, api_client, seeded):
        workspace, _ = seeded
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id)})
        assert response.status_code == 401

    def test_missing_workspace_id_returns_400(self, api_client, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(FEED_URL, {})
        assert response.status_code == 400

    def test_non_member_returns_403(self, api_client, user_factory, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(user_factory())
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id)})
        assert response.status_code == 403

    def test_owner_can_read(self, api_client, seeded):
        workspace, entries = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id)})
        assert response.status_code == 200
        assert response.data["count"] == 3
        assert {row["id"] for row in response.data["results"]} == {str(e.id) for e in entries}

    def test_auditor_viewer_member_can_read(self, api_client, user_factory, seeded):
        workspace, _ = seeded
        auditor = user_factory()
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=auditor,
            role=WorkspaceMembership.Role.VIEWER,
            persona=WorkspaceMembership.Persona.AUDITOR,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        api_client.force_authenticate(auditor)
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id)})
        assert response.status_code == 200
        assert response.data["count"] == 3

    def test_post_is_not_allowed(self, api_client, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.post(f"{FEED_URL}?workspace_id={workspace.id}", {})
        assert response.status_code == 405


class TestWorkspaceScoping:
    def test_other_tenants_rows_are_excluded(self, api_client, workspace_factory, seeded):
        workspace, _ = seeded
        other = workspace_factory()
        _log(other, other.workspace_owner)

        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id)})
        assert response.status_code == 200
        assert response.data["count"] == 3

    def test_null_workspace_rows_are_excluded(self, api_client, seeded):
        workspace, _ = seeded
        ct = ContentType.objects.get_for_model(Workspace)
        EntityAuditLog.objects.create(
            workspace=None,
            content_type=ct,
            object_id=str(workspace.id),
            field_name="workspace_name",
            previous_value="x",
            new_value="y",
        )
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id)})
        assert response.data["count"] == 3


class TestFiltersAndPagination:
    def test_field_name_filter(self, api_client, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id), "field_name": "status"})
        assert response.data["count"] == 1
        assert response.data["results"][0]["field_name"] == "status"

    def test_entity_type_filter(self, api_client, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(
            FEED_URL,
            {"workspace_id": str(workspace.id), "entity_type": _workspace_entity_type()},
        )
        assert response.data["count"] == 3

    def test_unknown_entity_type_filter_returns_empty(self, api_client, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(
            FEED_URL,
            {"workspace_id": str(workspace.id), "entity_type": "nope.nothing"},
        )
        assert response.status_code == 200
        assert response.data["count"] == 0
        assert response.data["results"] == []

    def test_actor_filter(self, api_client, user_factory, seeded):
        workspace, _ = seeded
        other_actor = user_factory()
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=other_actor,
            role=WorkspaceMembership.Role.VIEWER,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        _log(workspace, other_actor, field_name="privacy")

        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id), "actor_id": str(other_actor.id)})
        assert response.data["count"] == 1
        assert response.data["results"][0]["actor_display"]

    def test_since_until_window(self, api_client, seeded):
        workspace, entries = seeded
        old = entries[0]
        EntityAuditLog.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=30))
        api_client.force_authenticate(workspace.workspace_owner)
        since = (timezone.now() - timedelta(days=1)).isoformat()
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id), "since": since})
        assert response.data["count"] == 2

        until = (timezone.now() - timedelta(days=2)).isoformat()
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id), "until": until})
        assert response.data["count"] == 1

    def test_pagination_envelope(self, api_client, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id), "limit": 2, "page": 2})
        assert response.data["count"] == 3
        assert response.data["page"] == 2
        assert response.data["limit"] == 2
        assert len(response.data["results"]) == 1

    def test_newest_first(self, api_client, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(FEED_URL, {"workspace_id": str(workspace.id)})
        stamps = [row["created_at"] for row in response.data["results"]]
        assert stamps == sorted(stamps, reverse=True)


class TestPerEntityEndpointGate:
    """The per-entity read shares the tenant gate: explicit workspace_id
    + membership, and rows are scoped to that workspace."""

    def test_missing_workspace_id_returns_400(self, api_client, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(
            ENTITY_URL,
            {"entity_type": _workspace_entity_type(), "object_id": str(workspace.id)},
        )
        assert response.status_code == 400

    def test_non_member_returns_403(self, api_client, user_factory, seeded):
        workspace, _ = seeded
        api_client.force_authenticate(user_factory())
        response = api_client.get(
            ENTITY_URL,
            {
                "workspace_id": str(workspace.id),
                "entity_type": _workspace_entity_type(),
                "object_id": str(workspace.id),
            },
        )
        assert response.status_code == 403

    def test_member_reads_entity_history(self, api_client, seeded):
        workspace, entries = seeded
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(
            ENTITY_URL,
            {
                "workspace_id": str(workspace.id),
                "entity_type": _workspace_entity_type(),
                "object_id": str(workspace.id),
            },
        )
        assert response.status_code == 200
        assert {row["id"] for row in response.data} == {str(e.id) for e in entries}

    def test_cross_tenant_entity_read_is_scoped(self, api_client, workspace_factory, seeded):
        """Naming your own workspace but another tenant's entity yields
        nothing — the repository filters rows to the named workspace."""
        workspace, _ = seeded
        other = workspace_factory()
        _log(other, other.workspace_owner)

        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.get(
            ENTITY_URL,
            {
                "workspace_id": str(workspace.id),
                "entity_type": _workspace_entity_type(),
                "object_id": str(other.id),
            },
        )
        assert response.status_code == 200
        assert response.data == []
