"""Domain service: derive a full semantic token set from a brand seed.

Policy for *which* tokens exist and how the seed becomes an accessible palette.
The colour maths (contrast, lightness, hue) is delegated to ``ColorSpacePort``;
the WCAG guarantee is delegated to ``WcagContrastPolicy``. Framework-free.
"""

from __future__ import annotations

from components.workspace.application.ports.color_space_port import ColorSpacePort
from components.workspace.domain.policies.wcag_contrast_policy import WcagContrastPolicy
from components.workspace.domain.value_objects.brand_seed import BrandSeed
from components.workspace.domain.value_objects.semantic_token_set import SemanticTokenSet

# When a workspace gives only a primary, derive the secondary by a small hue
# rotation (an analogous accent). Tertiary is a darker shade of the secondary
# (the far end of the brand gradient).
_SECONDARY_HUE_SHIFT = 28.0
_TERTIARY_DARKEN = -0.12


class BrandResolutionService:
    def __init__(self, color_space: ColorSpacePort, contrast_policy: WcagContrastPolicy) -> None:
        self._cs = color_space
        self._policy = contrast_policy

    def resolve(self, seed: BrandSeed) -> SemanticTokenSet:
        primary_bg, primary_fg = self._policy.accessible_pair(seed.primary)

        secondary_seed = seed.secondary or self._cs.rotate_hue(seed.primary, _SECONDARY_HUE_SHIFT)
        secondary_bg, secondary_fg = self._policy.accessible_pair(secondary_seed)

        tertiary = self._cs.adjust_lightness(secondary_bg, _TERTIARY_DARKEN)

        brand = {
            "primary": primary_bg,
            "primary-foreground": primary_fg,
            "secondary": secondary_bg,
            "secondary-foreground": secondary_fg,
            "tertiary": tertiary,
            "accent": secondary_bg,
            "accent-foreground": secondary_fg,
            "ring": primary_bg,
        }
        return SemanticTokenSet(brand=brand)
