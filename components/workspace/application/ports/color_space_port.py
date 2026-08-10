"""Port: colour-space primitives for brand palette resolution.

The domain ``BrandResolutionService`` owns the *policy* (which tokens exist, the
WCAG contrast target, how a seed is nudged to stay legible). The low-level
colour maths — sRGB luminance, HSL lightness/hue adjustment — is infrastructure
and lives behind this port, so the domain stays framework/library-free (manifesto
Rule 2) and the maths library is swappable (Rule 5). The default adapter is pure
stdlib; an OKLCH/``coloraide`` adapter can replace it without touching the domain.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ColorSpacePort(ABC):
    @abstractmethod
    def normalize_hex(self, hex_color: str) -> str:
        """Return a canonical ``#RRGGBB`` (upper-case, expands shorthand)."""

    @abstractmethod
    def to_channels(self, hex_color: str) -> str:
        """Return space-separated sRGB channels, e.g. ``"66 185 143"``."""

    @abstractmethod
    def contrast_ratio(self, hex_a: str, hex_b: str) -> float:
        """WCAG 2.x contrast ratio between two colours (1.0–21.0)."""

    @abstractmethod
    def adjust_lightness(self, hex_color: str, delta: float) -> str:
        """Shift HSL lightness by ``delta`` (−1.0…1.0), clamped; return hex."""

    @abstractmethod
    def rotate_hue(self, hex_color: str, degrees: float) -> str:
        """Rotate the HSL hue by ``degrees`` (used to derive a secondary)."""

    @abstractmethod
    def blend(self, foreground: str, background: str, alpha: float) -> str:
        """Composite ``foreground`` over ``background`` at ``alpha`` (0.0–1.0).

        Models what a browser paints for a translucent fill (``bg-accent/10``
        over a panel). The UI-accent derivation needs it because the surface an
        accent lands on is partly *made of* that accent.
        """

    @abstractmethod
    def lightness(self, hex_color: str) -> float:
        """HSL lightness (0.0–1.0) — used to pick which way to nudge a colour."""
