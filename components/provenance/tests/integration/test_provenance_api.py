"""Integration tests for the provenance graph REST surface.

Exercises the four read endpoints end to end: permission (active membership),
feature-flag gating, and the serialized response shapes.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from infrastructure.persistence.core.models import FeatureFlag
from infrastructure.persistence.provenance.models import (
    AccessGrant,
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_FLAG = "feature.provenance_graph"


def _enable_flag():
    FeatureFlag.objects.get_or_create(key=_FLAG, defaults={"default_enabled": True})


def _seed_graph(ws):
    actor = ProvenanceActor.objects.create(
        workspace=ws,
        actor_type="vendor_integration",
        source_system="aws",
        external_ref="arn:role/x",
        display_name="Vendor",
    )
    resource = ProvenanceResource.objects.create(
        workspace=ws,
        resource_type="s3_bucket",
        source_system="aws",
        external_ref="s3://b",
        display_name="b",
    )
    AccessGrant.objects.create(workspace=ws, actor=actor, resource=resource, permissions=["read", "admin"], scope="")
    ProvenanceEvent.objects.create(
        workspace=ws,
        actor=actor,
        resource=resource,
        action="AssumeRole",
        occurred_at=timezone.now(),
        source_system="aws",
        origin="audit_log",
        origin_id="e1",
    )
    return actor, resource


def _client(ws):
    client = APIClient()
    client.force_authenticate(user=ws.workspace_owner)
    return client


def test_blast_radius_endpoint_returns_graph(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    actor, _ = _seed_graph(ws)

    url = reverse("provenance-blast-radius", kwargs={"workspace_id": str(ws.id), "actor_id": str(actor.id)})
    resp = _client(ws).get(url)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["actor"]["external_ref"] == "arn:role/x"
    assert len(data["grants"]) == 1
    assert data["grants"][0]["is_admin"] is True


def test_access_review_endpoint_returns_rows(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    _, resource = _seed_graph(ws)

    url = reverse("provenance-access-review", kwargs={"workspace_id": str(ws.id), "resource_id": str(resource.id)})
    resp = _client(ws).get(url)

    assert resp.status_code == 200
    rows = resp.json()["data"]["rows"]
    assert len(rows) == 1
    assert rows[0]["last_activity_at"] is not None


def test_hall_tree_endpoint_returns_touched_resources(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    actor, _ = _seed_graph(ws)

    url = reverse("provenance-hall-tree", kwargs={"workspace_id": str(ws.id), "actor_id": str(actor.id)})
    resp = _client(ws).get(url)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["roots"]) == 1
    assert data["roots"][0]["event_count"] == 1


def test_least_privilege_endpoint_returns_gaps_list(workspace_factory):
    ws = workspace_factory()
    _enable_flag()
    _seed_graph(ws)

    url = reverse("provenance-least-privilege", kwargs={"workspace_id": str(ws.id)})
    resp = _client(ws).get(url)

    assert resp.status_code == 200
    assert "gaps" in resp.json()["data"]


def test_blast_radius_unknown_actor_is_404(workspace_factory):
    ws = workspace_factory()
    _enable_flag()

    url = reverse("provenance-blast-radius", kwargs={"workspace_id": str(ws.id), "actor_id": str(uuid4())})
    resp = _client(ws).get(url)

    assert resp.status_code == 404


def test_all_views_are_feature_gated_and_membership_scoped():
    """Deterministic wiring check: every endpoint declares the flag gate + the
    active-membership permission. (Runtime deny can't be exercised in DEBUG/test
    where flags fail open; RequiresFeatureFlag's own runtime is platform-tested.)
    """
    from components.provenance.api.controller import (
        AccessReviewView,
        HallTreeView,
        LeastPrivilegeView,
        VendorBlastRadiusView,
    )
    from components.shared_platform.api.permissions import HasWorkspaceMembership, RequiresFeatureFlag

    for view in (VendorBlastRadiusView, AccessReviewView, HallTreeView, LeastPrivilegeView):
        assert view.feature_flag_key == _FLAG
        assert RequiresFeatureFlag in view.permission_classes
        assert HasWorkspaceMembership in view.permission_classes
