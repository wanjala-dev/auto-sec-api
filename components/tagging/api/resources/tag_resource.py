"""Output DTO for the tag CRUD API — maps a TagEntity to a JSON-safe dict."""

from __future__ import annotations

from components.tagging.domain.entities.tag_entity import TagEntity


class TagResource:
    @staticmethod
    def from_entity(tag: TagEntity) -> dict:
        data = {
            "id": str(tag.id),
            "name": tag.name,
            "slug": tag.slug,
            "namespace": tag.namespace,
            "color": tag.color,
            "description": tag.description,
            "kind": tag.kind,
            "is_deleted": tag.is_deleted,
        }
        if tag.usage_count is not None:
            data["usage_count"] = tag.usage_count
        return data

    @staticmethod
    def page(items: list[TagEntity], total: int) -> dict:
        return {"items": [TagResource.from_entity(t) for t in items], "total": total}
