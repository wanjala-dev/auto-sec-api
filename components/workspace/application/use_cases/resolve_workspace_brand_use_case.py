"""Use case: resolve a workspace's brand to a token payload (implements
``BrandResolutionPort``).

Loads the stored seed (or the default when unthemed), runs the domain
resolver, and formats each token to the requested output shape (CSS channels
for the app, hex for email/PDF). Framework-free.

Payload contract: the ``mode`` / ``logo_url`` / ``light`` / ``dark`` shapes are
FROZEN (frontend, email, and PDF consumers all parse them) — new data may only
ever be added as additive top-level keys (``logos``, ``fonts``).
"""

from __future__ import annotations

from uuid import UUID

from components.workspace.application.ports.brand_resolution_port import BrandResolutionPort
from components.workspace.application.ports.color_space_port import ColorSpacePort
from components.workspace.application.ports.font_catalog_port import FontCatalogPort, FontOption
from components.workspace.application.ports.workspace_theme_store_port import WorkspaceThemeStorePort
from components.workspace.domain.services.brand_resolution_service import BrandResolutionService
from components.workspace.domain.value_objects.brand_seed import BrandSeed
from components.workspace.domain.value_objects.font_tokens import (
    DEFAULT_BODY,
    DEFAULT_HEADING,
    FontToken,
)
from components.workspace.domain.value_objects.semantic_token_set import (
    BrandOutputShape,
    SemanticTokenSet,
)

_DEFAULT_RADIUS = "0.5rem"
_DEFAULT_MODE = "light"


class ResolveWorkspaceBrandUseCase(BrandResolutionPort):
    def __init__(
        self,
        store: WorkspaceThemeStorePort,
        resolution_service: BrandResolutionService,
        color_space: ColorSpacePort,
        font_catalog: FontCatalogPort,
    ) -> None:
        self._store = store
        self._service = resolution_service
        self._cs = color_space
        self._fonts = font_catalog

    def resolve(self, workspace_id: UUID, output_shape: BrandOutputShape = BrandOutputShape.CSS) -> dict:
        stored = self._store.find_by_workspace(workspace_id)

        if stored and stored.brand_seed.strip():
            token_set = self._service.resolve(
                BrandSeed(primary=stored.brand_seed, secondary=stored.secondary_seed or None)
            )
        else:
            token_set = SemanticTokenSet.default()

        logo_url = stored.logo_url if stored else ""
        mode = (stored.mode if stored else "") or _DEFAULT_MODE
        radius = (stored.radius if stored else "") or _DEFAULT_RADIUS

        return {
            "mode": mode,
            "logo_url": logo_url,
            "light": self._format(token_set.light, output_shape, radius),
            "dark": self._format(token_set.dark, output_shape, radius),
            # Additive keys (brand-kit expansion). Font stacks are identical in
            # both output shapes — only colour formatting differs per consumer.
            "logos": {
                "primary": logo_url,
                "icon": stored.logo_icon_url if stored else "",
                "dark": stored.logo_dark_url if stored else "",
                "favicon": stored.favicon_url if stored else "",
            },
            "fonts": {
                "heading": self._font_token(stored.font_heading if stored else "", DEFAULT_HEADING).as_dict(),
                "body": self._font_token(stored.font_body if stored else "", DEFAULT_BODY).as_dict(),
            },
        }

    def _font_token(self, key: str, default: FontToken) -> FontToken:
        """Resolve a stored catalog key to a full font token.

        A blank key, an unknown key (catalog drift), or an unseeded catalog all
        fall back to the default — font lookup is decoration and must never
        break brand resolution.
        """
        if not key or not key.strip():
            return default
        option: FontOption | None = None
        try:
            option = self._fonts.find_by_key(key.strip())
        except Exception:
            option = None
        if option is None:
            return default
        return FontToken(
            family=option.label,
            stack=option.css_stack,
            google_family=option.google_family,
        )

    def _format(self, tokens: dict, shape: BrandOutputShape, radius: str) -> dict:
        formatted = {}
        for key, value in tokens.items():
            if key == "radius":
                formatted[key] = radius
            elif shape == BrandOutputShape.CSS:
                formatted[key] = self._cs.to_channels(value)
            else:
                formatted[key] = self._cs.normalize_hex(value)
        return formatted
