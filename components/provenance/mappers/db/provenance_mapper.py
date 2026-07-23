"""Mechanical ORM ↔ domain-entity translation for the provenance graph.

Mappers may import ORM models (they are the seam between persistence and the
domain). No business logic here — pure translation.
"""

from __future__ import annotations

from components.provenance.domain.entities.actor_entity import ActorEntity
from components.provenance.domain.entities.grant_entity import GrantEntity
from components.provenance.domain.entities.provenance_event_entity import ProvenanceEventEntity
from components.provenance.domain.entities.resource_entity import ResourceEntity
from components.provenance.domain.value_objects.enums import (
    ActorType,
    PermissionLevel,
    SourceSystem,
)


def to_actor_entity(model) -> ActorEntity:
    return ActorEntity(
        id=model.id,
        workspace_id=model.workspace_id,
        actor_type=ActorType(model.actor_type),
        source_system=SourceSystem(model.source_system),
        external_ref=model.external_ref,
        display_name=model.display_name,
        user_id=model.user_id,
        agent_ref=model.agent_ref,
        integration_ref=model.integration_ref,
        is_active=model.is_active,
    )


def to_resource_entity(model) -> ResourceEntity:
    return ResourceEntity(
        id=model.id,
        workspace_id=model.workspace_id,
        resource_type=model.resource_type,
        source_system=SourceSystem(model.source_system),
        external_ref=model.external_ref,
        display_name=model.display_name,
    )


def to_grant_entity(model) -> GrantEntity:
    return GrantEntity(
        id=model.id,
        workspace_id=model.workspace_id,
        actor_id=model.actor_id,
        resource_id=model.resource_id,
        permissions=tuple(PermissionLevel(p) for p in (model.permissions or [])),
        scope=model.scope,
        source=model.source,
        is_active=model.revoked_at is None,
    )


def to_event_entity(model) -> ProvenanceEventEntity:
    return ProvenanceEventEntity(
        id=model.id,
        workspace_id=model.workspace_id,
        actor_id=model.actor_id,
        resource_id=model.resource_id,
        action=model.action,
        occurred_at=model.occurred_at,
        source_system=SourceSystem(model.source_system),
        origin=model.origin,
        origin_id=model.origin_id,
        metadata=model.metadata or {},
    )
