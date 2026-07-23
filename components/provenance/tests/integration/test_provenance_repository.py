"""Integration tests for :class:`DjangoProvenanceRepository` — real DB.

Seeds provenance rows directly (backfill from EntityAuditLog / AI actions /
identity is a later sub-slice) and asserts the four read queries return the
deterministic shapes the HUD + findings pipeline consume.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from components.provenance.infrastructure.repositories.django_provenance_repository import (
    DjangoProvenanceRepository,
)
from infrastructure.persistence.provenance.models import (
    AccessGrant,
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = timezone.now()


def _actor(ws, *, actor_type="vendor_integration", source="aws", ref="arn:role/x", name="Vendor"):
    return ProvenanceActor.objects.create(
        workspace=ws, actor_type=actor_type, source_system=source, external_ref=ref, display_name=name
    )


def _resource(ws, *, rtype="s3_bucket", source="aws", ref="s3://bucket-a", name="bucket-a"):
    return ProvenanceResource.objects.create(
        workspace=ws, resource_type=rtype, source_system=source, external_ref=ref, display_name=name
    )


def _grant(ws, actor, resource, *, permissions=("read",), scope="", revoked_at=None):
    return AccessGrant.objects.create(
        workspace=ws,
        actor=actor,
        resource=resource,
        permissions=list(permissions),
        scope=scope,
        revoked_at=revoked_at,
    )


def _event(ws, actor, resource, *, action="AssumeRole", when=None, origin="audit_log", origin_id="e1"):
    return ProvenanceEvent.objects.create(
        workspace=ws,
        actor=actor,
        resource=resource,
        action=action,
        occurred_at=when or _NOW,
        source_system="aws",
        origin=origin,
        origin_id=origin_id,
    )


def test_vendor_blast_radius_returns_grants_events_and_reachable(workspace_factory):
    ws = workspace_factory()
    actor = _actor(ws)
    r1, r2 = _resource(ws, ref="s3://a"), _resource(ws, ref="s3://b", name="bucket-b")
    _grant(ws, actor, r1)
    _grant(ws, actor, r2, permissions=("read", "admin"))
    _event(ws, actor, r1, origin_id="ev-1")
    _event(ws, actor, r2, origin_id="ev-2", when=_NOW - timedelta(hours=1))

    result = DjangoProvenanceRepository().vendor_blast_radius(workspace_id=ws.id, actor_id=actor.id)

    assert result.actor.external_ref == "arn:role/x"
    assert len(result.grants) == 2
    assert len(result.reachable_resources) == 2
    # Recent events ordered newest-first.
    assert [e.origin_id for e in result.recent_events] == ["ev-1", "ev-2"]


def test_access_review_lists_actors_with_last_activity(workspace_factory):
    ws = workspace_factory()
    resource = _resource(ws)
    active_actor = _actor(ws, ref="arn:role/active")
    dormant_actor = _actor(ws, ref="arn:role/dormant")
    _grant(ws, active_actor, resource)
    _grant(ws, dormant_actor, resource)
    _event(ws, active_actor, resource, origin_id="ev-active")

    rows = DjangoProvenanceRepository().access_review(workspace_id=ws.id, resource_id=resource.id)

    by_ref = {row.actor.external_ref: row for row in rows}
    assert len(rows) == 2
    assert by_ref["arn:role/active"].last_activity_at is not None
    assert by_ref["arn:role/dormant"].last_activity_at is None


def test_hall_tree_groups_touched_resources_since_window(workspace_factory):
    ws = workspace_factory()
    actor = _actor(ws)
    r1, r2 = _resource(ws, ref="s3://a"), _resource(ws, ref="s3://b", name="bucket-b")
    since = _NOW - timedelta(days=7)
    _event(ws, actor, r1, origin_id="e1", when=_NOW - timedelta(days=1))
    _event(ws, actor, r1, origin_id="e2", when=_NOW - timedelta(hours=2))
    _event(ws, actor, r2, origin_id="e3", when=_NOW - timedelta(days=3))
    # Outside the window — must be excluded.
    _event(ws, actor, r2, origin_id="e-old", when=_NOW - timedelta(days=30))

    tree = DjangoProvenanceRepository().hall_tree(workspace_id=ws.id, actor_id=actor.id, since=since)

    counts = {node.resource.external_ref: node.event_count for node in tree.roots}
    assert counts == {"s3://a": 2, "s3://b": 1}
    # Sorted by most-recent activity first — r1 was touched 2h ago, r2 3 days ago.
    assert tree.roots[0].resource.external_ref == "s3://a"


def test_least_privilege_gaps_flags_unused_grants(workspace_factory):
    ws = workspace_factory()
    used_resource = _resource(ws, ref="s3://used")
    unused_resource = _resource(ws, ref="s3://unused", name="unused")
    actor = _actor(ws)
    _grant(ws, actor, used_resource)
    _grant(ws, actor, unused_resource)
    _event(ws, actor, used_resource, origin_id="ev-used", when=_NOW - timedelta(days=1))

    gaps = DjangoProvenanceRepository().least_privilege_gaps(workspace_id=ws.id, unused_days=30)

    flagged = {gap.resource.external_ref for gap in gaps}
    assert flagged == {"s3://unused"}
    assert gaps[0].unused_days == 30
