"""Domain service: derive a legible UI accent from a brand seed, per theme.

``BrandResolutionService`` answers "what text can sit ON the brand colour?"
(a fill + its foreground). This service answers the other, previously
unguarded question: **"can the brand colour itself be read as text on OUR
canvas?"** — because that is how the app consumes it. The HUD repoints its
accent token to the workspace's brand, and that token is a *text* colour on
~225 call sites as well as chrome.

Without this guard the app inherits whatever the customer picked: a brand
colour of ``#345700`` measured **1.87:1** on the dark HUD — unreadable, and it
reads as our bug rather than their colour choice.

Two roles, deliberately separated (the raw colour is not discarded):

* ``text``       — the readable variant. WCAG AA (4.5:1) against every surface
                   of that theme. Used wherever the accent renders TEXT or
                   meaningful UI state.
* ``decorative`` — the raw brand colour, nudged only if it fails the WCAG 1.4.11
                   non-text bar (3:1). Used for fills, borders, chips, glows —
                   the surfaces that carry brand identity rather than meaning.

For most brands ``decorative`` IS the untouched seed and only ``text`` moves;
for a mid-tone brand neither moves. The guard is minimum-intervention by
construction.

Framework-free — colour maths is delegated to ``ColorSpacePort``.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.workspace.application.ports.color_space_port import ColorSpacePort
from components.workspace.domain.policies.wcag_contrast_policy import WcagContrastPolicy
from components.workspace.domain.value_objects.ui_surface_palette import UiSurfacePalette

# Lightness step per iteration. 2% is fine enough that the accepted colour is
# visibly the brand (never an over-correction) and coarse enough to terminate
# quickly; 50 steps covers the full 0.0–1.0 lightness range.
_STEP = 0.02
_MAX_STEPS = 50


@dataclass(frozen=True)
class DerivedUiAccent:
    """One theme's accent pair plus whether the brand had to be nudged."""

    text: str
    decorative: str
    adjusted: bool
    text_ratio: float
    decorative_ratio: float


class UiAccentDerivationService:
    TEXT_TARGET = WcagContrastPolicy.AA_NORMAL  # 4.5:1 — WCAG 1.4.3 normal text
    DECORATIVE_TARGET = WcagContrastPolicy.AA_LARGE  # 3.0:1 — WCAG 1.4.11 non-text

    def __init__(self, color_space: ColorSpacePort, contrast_policy: WcagContrastPolicy) -> None:
        self._cs = color_space
        self._policy = contrast_policy

    def derive(self, seed: str, palette: UiSurfacePalette) -> DerivedUiAccent:
        normalized = self._cs.normalize_hex(seed)
        text = self._nudge_until_legible(normalized, palette, self.TEXT_TARGET)
        decorative = self._nudge_until_legible(normalized, palette, self.DECORATIVE_TARGET)
        return DerivedUiAccent(
            text=text,
            decorative=decorative,
            adjusted=text != normalized or decorative != normalized,
            text_ratio=self._policy.worst_contrast(text, self._backgrounds(text, palette)),
            decorative_ratio=self._policy.worst_contrast(decorative, self._backgrounds(decorative, palette)),
        )

    def _backgrounds(self, accent: str, palette: UiSurfacePalette) -> tuple[str, ...]:
        """Every surface this accent lands on, including the fills it tints itself.

        Accent-derived surfaces move WITH the accent, so they are recomputed for
        each candidate rather than measured once against the seed. Two kinds:

        * lightly tinted fills — the accent laid over a panel at a low alpha;
        * card interiors — ``HudCard`` paints an accent border layer and lays a
          translucent panel fill over it, so the accent tints the whole interior.
        """
        tinted = tuple(self._cs.blend(accent, s, palette.tint_alpha) for s in palette.surfaces)
        card_border = self._cs.blend(accent, palette.canvas, palette.card_border_alpha)
        cards = tuple(self._cs.blend(s, card_border, palette.card_fill_alpha) for s in palette.surfaces)
        return palette.surfaces + tinted + cards

    def _nudge_until_legible(self, seed: str, palette: UiSurfacePalette, target: float) -> str:
        """Move ONLY lightness, in the one direction that gains contrast.

        Hue and saturation are preserved, so a brand-navy workspace still reads
        brand-navy — it just becomes a lighter navy on the dark canvas.
        """
        if self._policy.worst_contrast(seed, self._backgrounds(seed, palette)) >= target:
            return seed

        # A dark canvas can only be escaped upward, a light canvas downward.
        direction = _STEP if self._cs.lightness(palette.canvas) < 0.5 else -_STEP

        candidate = seed
        for _ in range(_MAX_STEPS):
            candidate = self._cs.adjust_lightness(candidate, direction)
            if self._policy.worst_contrast(candidate, self._backgrounds(candidate, palette)) >= target:
                return candidate

        # Lightness saturated at pure white / pure black. Both clear the bar
        # against their opposing canvas by a wide margin, so this is a floor,
        # not a silent failure — but return the best-contrast endpoint rather
        # than an off-by-one from the loop.
        return candidate
