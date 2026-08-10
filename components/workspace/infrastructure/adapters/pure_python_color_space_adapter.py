"""Adapter: colour-space primitives implemented with the Python stdlib.

WCAG contrast (sRGB relative luminance) is exact and dependency-free; lightness
and hue adjustments use ``colorsys`` (HSL). An OKLCH/HSLuv adapter (e.g.
``coloraide``) can replace this behind ``ColorSpacePort`` for perceptually
uniform scales without touching the domain.
"""

from __future__ import annotations

import colorsys

from components.workspace.application.ports.color_space_port import ColorSpacePort


def _to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _clamp(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _to_hex(r: float, g: float, b: float) -> str:
    return f"#{_clamp(r):02X}{_clamp(g):02X}{_clamp(b):02X}"


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def _channel(value: int) -> float:
        c = value / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


class PurePythonColorSpaceAdapter(ColorSpacePort):
    def normalize_hex(self, hex_color: str) -> str:
        return _to_hex(*_to_rgb(hex_color))

    def to_channels(self, hex_color: str) -> str:
        r, g, b = _to_rgb(hex_color)
        return f"{r} {g} {b}"

    def contrast_ratio(self, hex_a: str, hex_b: str) -> float:
        la = _relative_luminance(_to_rgb(hex_a))
        lb = _relative_luminance(_to_rgb(hex_b))
        lighter, darker = (la, lb) if la >= lb else (lb, la)
        return (lighter + 0.05) / (darker + 0.05)

    def adjust_lightness(self, hex_color: str, delta: float) -> str:
        r, g, b = (c / 255.0 for c in _to_rgb(hex_color))
        h, lightness, s = colorsys.rgb_to_hls(r, g, b)
        lightness = max(0.0, min(1.0, lightness + delta))
        nr, ng, nb = colorsys.hls_to_rgb(h, lightness, s)
        return _to_hex(nr * 255, ng * 255, nb * 255)

    def rotate_hue(self, hex_color: str, degrees: float) -> str:
        r, g, b = (c / 255.0 for c in _to_rgb(hex_color))
        h, lightness, s = colorsys.rgb_to_hls(r, g, b)
        h = (h + degrees / 360.0) % 1.0
        nr, ng, nb = colorsys.hls_to_rgb(h, lightness, s)
        return _to_hex(nr * 255, ng * 255, nb * 255)

    def blend(self, foreground: str, background: str, alpha: float) -> str:
        a = max(0.0, min(1.0, alpha))
        fr, fg, fb = _to_rgb(foreground)
        br, bg, bb = _to_rgb(background)
        return _to_hex(
            fr * a + br * (1 - a),
            fg * a + bg * (1 - a),
            fb * a + bb * (1 - a),
        )

    def lightness(self, hex_color: str) -> float:
        r, g, b = (c / 255.0 for c in _to_rgb(hex_color))
        _, lightness, _ = colorsys.rgb_to_hls(r, g, b)
        return lightness
