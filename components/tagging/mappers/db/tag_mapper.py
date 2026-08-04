"""Mechanical ORM ↔ domain translation for Tag. No business logic."""

from __future__ import annotations

from components.tagging.domain.entities.tag_entity import TagEntity


def to_tag_entity(model, *, usage_count: int | None = None) -> TagEntity:
    if usage_count is None:
        usage_count = getattr(model, "usage_count", None)
    return TagEntity(
        id=model.id,
        workspace_id=model.workspace_id,
        name=model.name,
        slug=model.slug,
        namespace=model.namespace,
        color=model.color,
        description=model.description,
        kind=model.kind,
        is_deleted=model.is_deleted,
        created_at=model.created_at,
        updated_at=model.updated_at,
        usage_count=usage_count,
    )
