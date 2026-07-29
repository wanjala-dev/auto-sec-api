"""Port: resolve a workspace's brand to a ready-to-consume token payload.

This is the PUBLISHED inbound port other contexts consume (reports, content,
notifications, the identity bootstrap payload). Consumers import THIS port +
``BrandOutputShape`` (a domain value object) and the provider — never the
workspace repository or ORM model. See manifesto Rule 3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.workspace.domain.value_objects.semantic_token_set import BrandOutputShape


class BrandResolutionPort(ABC):
    @abstractmethod
    def resolve(self, workspace_id: UUID, output_shape: BrandOutputShape = BrandOutputShape.CSS) -> dict:
        """Return ``{mode, logo_url, light: {...}, dark: {...}}`` with token
        values in the requested shape (CSS channels for the app, hex for
        email/PDF). Falls back to the default brand when unthemed."""
