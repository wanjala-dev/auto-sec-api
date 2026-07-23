"""Pure unit tests for provenance domain entities — no DB, no framework."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.provenance.domain.entities.actor_entity import ActorEntity
from components.provenance.domain.entities.grant_entity import GrantEntity
from components.provenance.domain.entities.provenance_event_entity import ProvenanceEventEntity
from components.provenance.domain.entities.resource_entity import ResourceEntity
from components.provenance.domain.value_objects.enums import (
    ActorType,
    PermissionLevel,
    SourceSystem,
)

pytestmark = pytest.mark.unit


def _actor(**overrides) -> ActorEntity:
    base = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "actor_type": ActorType.VENDOR_INTEGRATION,
        "source_system": SourceSystem.AWS,
        "external_ref": "arn:aws:iam::123456789012:role/AutoSecAuditRole",
    }
    base.update(overrides)
    return ActorEntity(**base)


def test_actor_requires_external_ref():
    with pytest.raises(ValueError):
        _actor(external_ref="")


def test_resource_requires_type_and_ref():
    with pytest.raises(ValueError):
        ResourceEntity(
            id=uuid4(),
            workspace_id=uuid4(),
            resource_type="",
            source_system=SourceSystem.AWS,
            external_ref="s3://bucket",
        )


def test_grant_is_admin_reflects_permission_set():
    admin = GrantEntity(
        id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        resource_id=uuid4(),
        permissions=(PermissionLevel.READ, PermissionLevel.ADMIN),
    )
    read_only = GrantEntity(
        id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        resource_id=uuid4(),
        permissions=(PermissionLevel.READ,),
    )
    assert admin.is_admin is True
    assert read_only.is_admin is False


def test_event_metadata_is_immutable():
    event = ProvenanceEventEntity(
        id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        resource_id=uuid4(),
        action="AssumeRole",
        occurred_at=datetime(2026, 7, 23, tzinfo=UTC),
        source_system=SourceSystem.AWS,
        origin="audit_log",
        origin_id="evt-123",
        metadata={"ip": "10.0.0.1"},
    )
    assert event.metadata["ip"] == "10.0.0.1"
    with pytest.raises(TypeError):
        event.metadata["ip"] = "changed"  # type: ignore[index]


def test_event_requires_action_and_origin_id():
    with pytest.raises(ValueError):
        ProvenanceEventEntity(
            id=uuid4(),
            workspace_id=uuid4(),
            actor_id=uuid4(),
            resource_id=uuid4(),
            action="",
            occurred_at=datetime.now(UTC),
            source_system=SourceSystem.INTERNAL,
            origin="audit_log",
            origin_id="x",
        )
