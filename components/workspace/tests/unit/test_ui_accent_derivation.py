"""The customer-colour contrast guard.

Per-workspace branding repoints the HUD accent to whatever colour the customer
picked. Nothing guaranteed that colour was legible ON our canvas — a brand of
``#345700`` measured 1.87:1 live, i.e. invisible, and every design partner
brands their workspace.

These tests pin the guarantee for the colours most likely to break it:
near-black, near-white, saturated neon, mid greys, and the real 1.87:1 case.
"""

from __future__ import annotations

import pytest

from components.workspace.domain.policies.wcag_contrast_policy import WcagContrastPolicy
from components.workspace.domain.services.ui_accent_derivation_service import (
    UiAccentDerivationService,
)
from components.workspace.domain.value_objects.ui_surface_palette import (
    APP_SURFACE_PALETTES,
    DARK_HUD,
    LIGHT_HUD,
)
from components.workspace.infrastructure.adapters.pure_python_color_space_adapter import (
    PurePythonColorSpaceAdapter,
)

pytestmark = [pytest.mark.unit]

# The colours a real customer plausibly picks, plus the ones that break naive maths.
PATHOLOGICAL_SEEDS = [
    "#345700",  # the measured 1.87:1 live failure — dark olive
    "#000000",  # pure black
    "#0A0A0A",  # near-black
    "#FFFFFF",  # pure white
    "#FEFEFE",  # near-white
    "#808080",  # mid grey (worst case for BOTH themes)
    "#7F7F7F",
    "#39FF14",  # saturated neon green
    "#FF00FF",  # saturated magenta
    "#0000FF",  # pure blue — very low luminance despite full saturation
    "#1E3A8A",  # brand navy (the identity-preservation case)
    "#B22222",  # firebrick
    "#FFD700",  # gold — fails on light, passes on dark
    "#2EDBE8",  # autosec's own cyan (the control)
]


@pytest.fixture
def color_space():
    return PurePythonColorSpaceAdapter()


@pytest.fixture
def service(color_space):
    return UiAccentDerivationService(color_space, WcagContrastPolicy(color_space))


def _all_backgrounds(color_space, accent, palette):
    """Every surface the accent lands on, including the fill it tints itself."""
    tinted = tuple(color_space.blend(accent, s, palette.tint_alpha) for s in palette.surfaces)
    return palette.surfaces + tinted


class TestGuaranteedRatios:
    @pytest.mark.parametrize("seed", PATHOLOGICAL_SEEDS)
    @pytest.mark.parametrize("palette", APP_SURFACE_PALETTES, ids=lambda p: p.key)
    def test_text_accent_clears_aa_on_every_surface(self, service, color_space, seed, palette):
        derived = service.derive(seed, palette)

        for background in _all_backgrounds(color_space, derived.text, palette):
            ratio = color_space.contrast_ratio(derived.text, background)
            assert ratio >= UiAccentDerivationService.TEXT_TARGET, (
                f"{seed} -> {derived.text} only reaches {ratio:.2f}:1 on {background} ({palette.key} theme)"
            )

    @pytest.mark.parametrize("seed", PATHOLOGICAL_SEEDS)
    @pytest.mark.parametrize("palette", APP_SURFACE_PALETTES, ids=lambda p: p.key)
    def test_decorative_accent_clears_the_non_text_bar(self, service, color_space, seed, palette):
        """WCAG 1.4.11 — borders/fills only need 3:1, but they DO need 3:1.

        A near-black brand on the dark canvas made every hairline vanish; that
        is a real defect, not a taste call.
        """
        derived = service.derive(seed, palette)

        for background in _all_backgrounds(color_space, derived.decorative, palette):
            ratio = color_space.contrast_ratio(derived.decorative, background)
            assert ratio >= UiAccentDerivationService.DECORATIVE_TARGET, (
                f"{seed} -> {derived.decorative} only reaches {ratio:.2f}:1 on {background}"
            )

    def test_the_measured_live_failure_is_fixed(self, service, color_space):
        """The real regression: brand ``#345700`` (rgb 52 87 0).

        Measured live in the browser on the seeded workspace at 1.87:1 against
        the rendered surface it landed on; against the HUD's own surface tokens
        it computes 2.14–2.34:1. Either way it is far under the 4.5:1 bar and
        was shipping to every branded workspace.
        """
        policy = WcagContrastPolicy(color_space)
        before = policy.worst_contrast("#345700", _all_backgrounds(color_space, "#345700", DARK_HUD))
        assert before < 3.0, "fixture drift: this seed is supposed to be the broken one"

        derived = service.derive("#345700", DARK_HUD)

        assert derived.adjusted is True
        assert derived.text_ratio >= UiAccentDerivationService.TEXT_TARGET
        assert derived.text_ratio > before * 2


class TestBrandIdentityPreservation:
    @pytest.mark.parametrize("palette", APP_SURFACE_PALETTES, ids=lambda p: p.key)
    def test_hue_is_preserved_so_a_navy_brand_stays_navy(self, service, color_space, palette):
        derived = service.derive("#1E3A8A", palette)

        # Blue stays the dominant channel — the accent still reads as the brand.
        r, g, b = (int(c) for c in color_space.to_channels(derived.text).split())
        assert b > r and b > g, f"navy brand became {derived.text} on {palette.key}"

    def test_a_compliant_brand_is_returned_untouched(self, service):
        """Minimum intervention: if the colour already works, do not touch it."""
        derived = service.derive("#2EDBE8", DARK_HUD)

        assert derived.text == "#2EDBE8"
        assert derived.decorative == "#2EDBE8"
        assert derived.adjusted is False

    def test_decorative_stays_closer_to_the_seed_than_text(self, service, color_space):
        """The role split earns its keep: the raw colour survives on chrome.

        A gold brand needs a big move to be readable text on the light canvas
        but only a small one to be a visible border.
        """
        derived = service.derive("#FFD700", LIGHT_HUD)

        seed_l = color_space.lightness("#FFD700")
        assert abs(color_space.lightness(derived.decorative) - seed_l) < abs(
            color_space.lightness(derived.text) - seed_l
        )


class TestDirectionality:
    def test_a_dark_brand_is_lightened_for_the_dark_canvas(self, service, color_space):
        derived = service.derive("#0A0A0A", DARK_HUD)
        assert color_space.lightness(derived.text) > color_space.lightness("#0A0A0A")

    def test_a_light_brand_is_darkened_for_the_light_canvas(self, service, color_space):
        derived = service.derive("#FEFEFE", LIGHT_HUD)
        assert color_space.lightness(derived.text) < color_space.lightness("#FEFEFE")

    def test_the_same_seed_resolves_differently_per_theme(self, service):
        """The guard is per-theme by construction — one value cannot serve both.

        This is the same conclusion the static tokens reached by hand
        (`#2EDBE8` dark / `#0b636b` light); branded workspaces now get it too.
        """
        dark = service.derive("#808080", DARK_HUD)
        light = service.derive("#808080", LIGHT_HUD)
        assert dark.text != light.text
