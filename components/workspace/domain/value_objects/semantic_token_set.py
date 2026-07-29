"""Value object: the resolved semantic token palette (the cross-context read
surface for per-workspace branding).

Only the brand tokens vary per workspace; neutrals and state colours are fixed —
a workspace recolours the accents, never the whole canvas or the meaning of
"error"/"success". The ``light``/``dark`` maps mirror ``:root`` / ``html.dark``
in the frontend's ``src/index.css``. Framework-free.

Design: docs/plans/WORKSPACE_THEMING_DESIGN_2026-07-09.md (source repo)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BrandOutputShape(Enum):
    """How resolved token values are formatted for a given consumer."""

    CSS = "css"  # space-separated sRGB channels, e.g. "66 185 143" (frontend :root)
    HEX = "hex"  # "#RRGGBB" (email + PDF, which cannot use CSS variables)


# Fixed neutral surfaces — NOT brand-derived. Default values; must match
# src/index.css so an unthemed workspace renders identically to today.
NEUTRALS_LIGHT = {
    "background": "#FFFFFF",
    "foreground": "#374557",
    "card": "#FFFFFF",
    "card-foreground": "#1E293B",
    "popover": "#FFFFFF",
    "popover-foreground": "#374557",
    "muted": "#F3F4F6",
    "muted-foreground": "#6B7280",
    "border": "#E5E5E5",
    "input": "#E5E5E5",
}
NEUTRALS_DARK = {
    "background": "#1D1F2F",
    "foreground": "#E2E8F0",
    "card": "#0F172A",
    "card-foreground": "#E2E8F0",
    "popover": "#1D1F2F",
    "popover-foreground": "#E2E8F0",
    "muted": "#1E2233",
    "muted-foreground": "#9AA3B1",
    "border": "#333650",
    "input": "#333650",
}
# State tokens are fixed — a workspace cannot recolour "error"/"success".
STATE = {
    "success": "#27AE60",
    "warning": "#F2994A",
    "destructive": "#EB5757",
    "destructive-foreground": "#FFFFFF",
}
RADIUS = "0.5rem"

# The default brand tokens — autosec's own HUD identity, so an unthemed
# workspace renders as the neon-cyan HUD it is today, and "Blue Team" IS this
# default palette (the Red-team flip overrides the same token names). Primary /
# ring are the HUD accent #2EDBE8; secondary is the HUD's purple. Foregrounds are
# pre-chosen WCAG-AA pairs — a user-supplied seed gets its pairs derived by
# BrandResolutionService instead.
DEFAULT_BRAND = {
    "primary": "#2EDBE8",
    "primary-foreground": "#04121F",
    "secondary": "#7C4DFF",
    "secondary-foreground": "#FFFFFF",
    "tertiary": "#5A34B8",
    "accent": "#7C4DFF",
    "accent-foreground": "#FFFFFF",
    "ring": "#2EDBE8",
}
BRAND_TOKEN_KEYS = tuple(DEFAULT_BRAND.keys())


@dataclass(frozen=True)
class SemanticTokenSet:
    """The resolved ~18-token semantic palette (hex), light + dark."""

    brand: dict

    @property
    def light(self) -> dict:
        return {**NEUTRALS_LIGHT, **STATE, **self.brand, "radius": RADIUS}

    @property
    def dark(self) -> dict:
        return {**NEUTRALS_DARK, **STATE, **self.brand, "radius": RADIUS}

    @classmethod
    def default(cls) -> SemanticTokenSet:
        """The default palette (autosec's HUD identity) for a workspace with no
        brand set — also the "Blue Team" base the Red-team flip overrides."""
        return cls(brand=dict(DEFAULT_BRAND))
