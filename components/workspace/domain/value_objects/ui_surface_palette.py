"""Value object: the app surfaces a brand accent is actually painted on.

Per-workspace branding repoints the HUD's accent token to the customer's brand
colour. Whether that colour is *legible* depends entirely on what it lands on —
so the derivation needs the real surfaces, not a nominal background.

These mirror the HUD tokens in the frontend's ``src/index.css``
(``--hud-canvas`` / ``--hud-surface`` / ``--hud-surface-2``), exactly as
``semantic_token_set.NEUTRALS_*`` mirrors the V1 app tokens. They are FIXED —
a workspace recolours the accent, never the canvas.

The remaining surfaces are not tokens at all — they are *made of the accent*,
which is why they are expressed as alphas and recomputed at every step of the
derivation rather than measured once:

* ``tint_alpha`` — lightly accent-tinted fills (``bg-hud-accent/[0.06…0.1]``).
  These were the worst-case surface in the static-token audit (frontend #175).
* ``card_border_alpha`` / ``card_fill_alpha`` — ``HudCard`` paints an accent
  border layer and lays a TRANSLUCENT panel fill over it, so the accent tints
  the whole card interior, not just the 1.5px rim. Modelled at the component's
  strongest border and its default fill. Verified against the rendered DOM:
  this reproduces the measured ``#1B3014`` exactly.

**Where the bar deliberately stops.** ``HudCard`` is also used with much thinner
fills (``bg-hud-surface/30…/60``), and there the accent bleeds through so
strongly that accent-coloured text cannot clear AA *for any colour* — autosec's
own built-in tokens measure 3.95:1 (cyan), 3.08:1 (red team) and 3.15:1 (light
teal) on that stack, and at ``/20`` even pure white tops out at 3.86:1. That is
a component defect in the card's border/fill combination, identical for branded
and unbranded workspaces, and it is not fixable by choosing a different accent.
Chasing it here would hold a customer's brand to a stricter bar than our own
palette meets while destroying the colour they picked. The bar modelled here is
therefore: **a branded accent must be at least as legible as autosec's own
accent is, on every surface where the colour is actually the right lever.**

Framework-free.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UiSurfacePalette:
    """One theme's opaque surfaces plus the accent-derived fills laid over them."""

    key: str
    canvas: str
    surfaces: tuple[str, ...]
    tint_alpha: float
    card_border_alpha: float
    card_fill_alpha: float

    def __post_init__(self) -> None:
        if not self.surfaces:
            raise ValueError("a surface palette needs at least one opaque surface")
        for alpha in (self.tint_alpha, self.card_border_alpha, self.card_fill_alpha):
            if not 0.0 <= alpha <= 1.0:
                raise ValueError("surface alphas must be between 0.0 and 1.0")


# The dark HUD (`:root`) — the default mode.
DARK_HUD = UiSurfacePalette(
    key="dark",
    canvas="#041225",  # --hud-canvas
    surfaces=("#041225", "#060C18", "#0A1424"),  # canvas, --hud-surface, --hud-surface-2
    tint_alpha=0.10,  # bg-hud-accent/[0.1] tinted fills
    card_border_alpha=0.60,  # HudCard border="cyan-strong" -> bg-hud-accent/60
    card_fill_alpha=0.85,  # HudCard default surface -> bg-hud-surface/85
)

# The daylight HUD (`.hud-light`).
LIGHT_HUD = UiSurfacePalette(
    key="light",
    canvas="#E6EBF1",  # --hud-canvas
    surfaces=("#E6EBF1", "#F4F7FA", "#E8EEF4"),
    tint_alpha=0.10,
    card_border_alpha=0.60,
    card_fill_alpha=0.85,
)

APP_SURFACE_PALETTES = (DARK_HUD, LIGHT_HUD)
