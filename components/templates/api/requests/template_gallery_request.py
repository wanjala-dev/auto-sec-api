"""Input DTO for the unified gallery read.

Parses the gallery query params (workspace scope + optional kind filter) off the
DRF request into a framework-free value object the controller hands to the
registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TemplateGalleryRequest:
    workspace_id: Optional[str]
    kind: Optional[str]

    @classmethod
    def from_query_params(cls, params) -> "TemplateGalleryRequest":
        return cls(
            workspace_id=params.get("workspace_id") or None,
            kind=params.get("kind") or None,
        )
