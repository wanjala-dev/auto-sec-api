"""Domain policy: WCAG accessibility for brand foreground/background pairs.

The accessibility *guarantee* of per-workspace theming lives here: given any
brand seed colour, produce a (background, foreground) pair that meets WCAG AA
(≥ 4.5:1), nudging the seed's lightness minimally when the raw colour cannot
carry legible text. Framework-free — colour maths is delegated to a port.
"""

from __future__ import annotations

from components.workspace.application.ports.color_space_port import ColorSpacePort


class WcagContrastPolicy:
    AA_NORMAL = 4.5
    AA_LARGE = 3.0

    _WHITE = "#FFFFFF"
    _NEAR_BLACK = "#0A0A0A"
    _STEP = 0.04
    _MAX_STEPS = 16

    def __init__(self, color_space: ColorSpacePort) -> None:
        self._cs = color_space

    def best_foreground(self, background: str) -> str:
        """The higher-contrast of white / near-black on ``background``."""
        white = self._cs.contrast_ratio(self._WHITE, background)
        black = self._cs.contrast_ratio(self._NEAR_BLACK, background)
        return self._WHITE if white >= black else self._NEAR_BLACK

    def is_accessible(self, foreground: str, background: str, target: float = AA_NORMAL) -> bool:
        return self._cs.contrast_ratio(foreground, background) >= target

    def worst_contrast(self, color: str, backgrounds: tuple[str, ...]) -> float:
        """The lowest contrast ``color`` reaches across ``backgrounds``.

        A colour is only as legible as the least-forgiving surface it lands on,
        so every guard in this codebase measures the worst case — never the
        canvas alone. (Frontend #175 learned this the expensive way: the worst
        surface for the dim token was an accent-tinted card fill, not the
        canvas.)
        """
        return min(self._cs.contrast_ratio(color, bg) for bg in backgrounds)

    def accessible_pair(self, seed: str, target: float = AA_NORMAL) -> tuple[str, str]:
        """Return ``(background, foreground)`` guaranteed to meet ``target``.

        Keeps the seed if it already carries legible text; otherwise darkens it
        toward white text (most brand colours are mid-tone), then lightens toward
        dark text as a fallback. Nudges lightness only — hue/chroma are preserved
        so the colour still reads as the brand.
        """
        normalized = self._cs.normalize_hex(seed)
        fg = self.best_foreground(normalized)
        if self.is_accessible(fg, normalized, target):
            return normalized, fg

        bg = normalized
        for _ in range(self._MAX_STEPS):
            bg = self._cs.adjust_lightness(bg, -self._STEP)
            if self.is_accessible(self._WHITE, bg, target):
                return bg, self._WHITE

        bg = normalized
        for _ in range(self._MAX_STEPS):
            bg = self._cs.adjust_lightness(bg, self._STEP)
            if self.is_accessible(self._NEAR_BLACK, bg, target):
                return bg, self._NEAR_BLACK

        # Extreme edge (e.g. a pure mid-grey): keep the seed with its best fg.
        return normalized, self.best_foreground(normalized)
