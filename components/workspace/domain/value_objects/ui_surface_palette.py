"""Value object: the app surfaces a brand accent is actually painted on.

Per-workspace branding repoints the HUD's accent token to the customer's brand
colour. Whether that colour is *legible* depends entirely on what it lands on —
so the derivation needs the real surfaces, not a nominal background.

These mirror the HUD tokens in the frontend's ``src/index.css``
(``--hud-canvas`` / ``--hud-surface`` / ``--hud-surface-2``), exactly as
``semantic_token_set.NEUTRALS_*`` mirrors the V1 app tokens. They are FIXED —
a workspace recolours the accent, never the canvas.

The fourth surface is not a token at all: accent-tinted card fills
(``bg-hud-accent/[0.06…0.1]`` over a panel). It is *derived from the accent
itself*, which is why it is expressed as an alpha rather than a hex — the
derivation recomputes it at every step. It was the worst-case surface in the
static-token audit (frontend #175), and it stayed the worst case here.

Framework-free.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UiSurfacePalette:
    """One theme's opaque surfaces plus the accent-tint alpha applied over them."""

    key: str
    canvas: str
    surfaces: tuple[str, ...]
    tint_alpha: float

    def __post_init__(self) -> None:
        if not self.surfaces:
            raise ValueError("a surface palette needs at least one opaque surface")
        if not 0.0 <= self.tint_alpha <= 1.0:
            raise ValueError("tint_alpha must be between 0.0 and 1.0")


# The dark HUD (`:root`) — the default mode.
DARK_HUD = UiSurfacePalette(
    key="dark",
    canvas="#041225",  # --hud-canvas
    surfaces=("#041225", "#060C18", "#0A1424"),  # canvas, --hud-surface, --hud-surface-2
    tint_alpha=0.10,  # bg-hud-accent/[0.1] card fills
)

# The daylight HUD (`.hud-light`).
LIGHT_HUD = UiSurfacePalette(
    key="light",
    canvas="#E6EBF1",  # --hud-canvas
    surfaces=("#E6EBF1", "#F4F7FA", "#E8EEF4"),
    tint_alpha=0.10,
)

APP_SURFACE_PALETTES = (DARK_HUD, LIGHT_HUD)
