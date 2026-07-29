"""Port: the curated brand-font catalog (outbound / driven).

The catalog is platform data (seeded via ``seed_brand_fonts``), not
workspace-scoped. Consumers resolve a stored catalog key to a full font
token; an unknown/blank key falls back to the defaults in
``font_tokens.DEFAULT_FONTS``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FontOption:
    """One catalog entry an admin can pick for heading and/or body."""

    key: str  # stable slug, e.g. "poppins"
    label: str  # display name, e.g. "Poppins"
    category: str  # "heading" | "body" | "both"
    css_stack: str  # full CSS font-family stack incl. fallbacks
    google_family: str  # Google Fonts css2 family spec, "" = system stack
    sort_order: int = 0


class FontCatalogPort(ABC):
    @abstractmethod
    def list_active(self) -> list[FontOption]: ...

    @abstractmethod
    def find_by_key(self, key: str) -> FontOption | None:
        """Return the active catalog entry for ``key``, or ``None``."""
