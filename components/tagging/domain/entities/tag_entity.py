"""TagEntity — one workspace-scoped vocabulary entry as a domain object (ADR 0015 D3).

Lean and immutable (aggregate-light): invariants in ``__post_init__``. The
cross-context read carrier is ``TagRef`` (shared kernel); this full entity stays
inside the tagging context's port surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from components.shared_kernel.domain.tagging import TagRef
from components.tagging.domain.constants import (
    MAX_NAME_LENGTH,
    VALID_KINDS,
)
from components.tagging.domain.value_objects.tag_slug import (
    NAMESPACE_RE,
    SLUG_RE,
    validate_color,
)


@dataclass(frozen=True)
class TagEntity:
    id: UUID
    workspace_id: UUID
    name: str
    slug: str
    namespace: str = ""
    color: str = ""
    description: str = ""
    kind: str = "user"
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Read-side annotation (CRUD list with include_usage) — not an invariant.
    usage_count: int | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("TagEntity.name is required")
        if len(self.name) > MAX_NAME_LENGTH:
            raise ValueError(f"TagEntity.name exceeds {MAX_NAME_LENGTH} characters")
        if not self.slug or not SLUG_RE.match(self.slug):
            raise ValueError(f"TagEntity.slug is not a normalized slug: {self.slug!r}")
        if self.namespace and not NAMESPACE_RE.match(self.namespace):
            raise ValueError(f"TagEntity.namespace is invalid: {self.namespace!r}")
        if self.namespace and not self.slug.startswith(f"{self.namespace}:"):
            raise ValueError("TagEntity.slug must carry its namespace prefix")
        if self.kind not in VALID_KINDS:
            raise ValueError(f"TagEntity.kind must be one of {sorted(VALID_KINDS)}")
        validate_color(self.color)

    @property
    def is_system(self) -> bool:
        return self.kind == "system"

    def to_ref(self) -> TagRef:
        return TagRef(id=self.id, slug=self.slug, name=self.name, color=self.color)
