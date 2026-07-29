"""Unit tests for the brand palette resolver (pure domain — no DB, no framework)."""

from __future__ import annotations

import pytest

from components.workspace.domain.errors import InvalidBrandSeedError
from components.workspace.domain.policies.wcag_contrast_policy import WcagContrastPolicy
from components.workspace.domain.services.brand_resolution_service import BrandResolutionService
from components.workspace.domain.value_objects.brand_seed import BrandSeed
from components.workspace.domain.value_objects.semantic_token_set import (
    NEUTRALS_LIGHT,
    SemanticTokenSet,
)
from components.workspace.infrastructure.adapters.pure_python_color_space_adapter import (
    PurePythonColorSpaceAdapter,
)

AA = WcagContrastPolicy.AA_NORMAL


@pytest.fixture
def color_space():
    return PurePythonColorSpaceAdapter()


@pytest.fixture
def resolver(color_space):
    return BrandResolutionService(color_space, WcagContrastPolicy(color_space))


class TestColorSpaceAdapter:
    def test_channels(self, color_space):
        assert color_space.to_channels("#42B98F") == "66 185 143"

    def test_normalize_expands_shorthand(self, color_space):
        assert color_space.normalize_hex("#abc") == "#AABBCC"

    def test_contrast_white_on_black_is_maximal(self, color_space):
        assert color_space.contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0, abs=0.1)

    def test_contrast_is_symmetric(self, color_space):
        assert color_space.contrast_ratio("#42B98F", "#FFFFFF") == color_space.contrast_ratio("#FFFFFF", "#42B98F")


class TestWcagContrastPolicy:
    def test_dark_seed_keeps_white_text(self, color_space):
        policy = WcagContrastPolicy(color_space)
        bg, fg = policy.accessible_pair("#0F766E")  # dark teal
        assert fg == "#FFFFFF"
        assert color_space.contrast_ratio(fg, bg) >= AA

    def test_light_seed_gets_dark_text(self, color_space):
        policy = WcagContrastPolicy(color_space)
        bg, fg = policy.accessible_pair("#FDE68A")  # pale yellow
        assert color_space.contrast_ratio(fg, bg) >= AA

    def test_midtone_seed_is_nudged_accessible(self, color_space):
        # A mid-tone brand that fails with either raw foreground must be nudged.
        policy = WcagContrastPolicy(color_space)
        bg, fg = policy.accessible_pair("#42B98F")
        assert color_space.contrast_ratio(fg, bg) >= AA


class TestBrandResolutionService:
    def test_resolves_accessible_full_palette(self, resolver, color_space):
        tokens = resolver.resolve(BrandSeed(primary="#3B82F6", secondary="#F59E0B"))
        assert isinstance(tokens, SemanticTokenSet)
        # Every brand fg/bg pair meets WCAG AA in both modes.
        for mode in (tokens.light, tokens.dark):
            assert color_space.contrast_ratio(mode["primary-foreground"], mode["primary"]) >= AA
            assert color_space.contrast_ratio(mode["secondary-foreground"], mode["secondary"]) >= AA

    def test_neutrals_untouched_by_brand(self, resolver):
        tokens = resolver.resolve(BrandSeed(primary="#3B82F6"))
        # A workspace brand recolours accents, never the canvas.
        assert tokens.light["background"] == NEUTRALS_LIGHT["background"]
        assert tokens.dark["foreground"] == "#E2E8F0"

    def test_secondary_derived_when_absent(self, resolver):
        tokens = resolver.resolve(BrandSeed(primary="#3B82F6"))
        assert tokens.light["secondary"] != tokens.light["primary"]

    def test_default_is_autosec_cyan(self):
        tokens = SemanticTokenSet.default()
        assert tokens.light["primary"] == "#2EDBE8"  # the HUD neon accent
        assert tokens.light["secondary"] == "#7C4DFF"  # the HUD purple
        assert tokens.dark["primary"] == "#2EDBE8"

    def test_default_foreground_is_accessible(self, color_space):
        # Solid bg-primary buttons need dark text on the bright cyan —
        # white fails WCAG AA on #2EDBE8, the dark HUD canvas passes.
        tokens = SemanticTokenSet.default()
        for mode in (tokens.light, tokens.dark):
            assert color_space.contrast_ratio(mode["primary-foreground"], mode["primary"]) >= AA

    def test_invalid_seed_rejected(self):
        with pytest.raises(InvalidBrandSeedError):
            BrandSeed(primary="not-a-color")
