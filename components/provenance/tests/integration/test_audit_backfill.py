"""Integration tests for the EntityAuditLog -> provenance graph backfill."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.contenttypes.models import ContentType

from components.provenance.infrastructure.services.audit_backfill_service import (
    backfill_from_audit_log,
)
from infrastructure.persistence.audit.models import EntityAuditLog
from infrastructure.persistence.provenance.models import (
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _audit(ws, user, ct, object_id, field_name):
    return EntityAuditLog.objects.create(
        workspace=ws,
        actor=user,
        content_type=ct,
        object_id=str(object_id),
        field_name=field_name,
        new_value="x",
    )


def test_backfill_projects_actors_resources_events(workspace_factory, user_factory):
    ws = workspace_factory()
    user = user_factory()
    ct = ContentType.objects.get_for_model(ws.__class__)
    other_id = uuid4()
    # Two edits on the same entity by the same actor -> 1 actor, 1 resource, 2 events.
    _audit(ws, user, ct, ws.id, "name")
    _audit(ws, user, ct, ws.id, "story")
    # A third edit on a different entity -> +1 resource, +1 event.
    _audit(ws, user, ct, other_id, "name")

    counts = backfill_from_audit_log(workspace_id=ws.id)

    assert counts == {"scanned": 3, "actors": 1, "resources": 2, "events": 3}
    actor = ProvenanceActor.objects.get(workspace=ws, source_system="internal")
    assert actor.actor_type == "human"
    assert actor.user_id == user.id
    assert ProvenanceResource.objects.filter(workspace=ws).count() == 2
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 3


def test_backfill_is_idempotent(workspace_factory, user_factory):
    ws = workspace_factory()
    user = user_factory()
    ct = ContentType.objects.get_for_model(ws.__class__)
    _audit(ws, user, ct, ws.id, "name")

    first = backfill_from_audit_log(workspace_id=ws.id)
    second = backfill_from_audit_log(workspace_id=ws.id)

    assert first == {"scanned": 1, "actors": 1, "resources": 1, "events": 1}
    assert second == {"scanned": 1, "actors": 0, "resources": 0, "events": 0}
    assert ProvenanceEvent.objects.filter(workspace=ws).count() == 1


def test_backfill_skips_rows_without_actor(workspace_factory):
    ws = workspace_factory()
    ct = ContentType.objects.get_for_model(ws.__class__)
    EntityAuditLog.objects.create(workspace=ws, actor=None, content_type=ct, object_id=str(ws.id), field_name="name")

    counts = backfill_from_audit_log(workspace_id=ws.id)

    assert counts == {"scanned": 0, "actors": 0, "resources": 0, "events": 0}
