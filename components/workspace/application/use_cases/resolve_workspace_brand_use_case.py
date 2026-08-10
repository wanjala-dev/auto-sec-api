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
from components.workspace.domain.services.ui_accent_derivation_service import (
    UiAccentDerivationService,
)
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
from components.workspace.domain.value_objects.ui_surface_palette import APP_SURFACE_PALETTES

_DEFAULT_RADIUS = "0.5rem"
_DEFAULT_MODE = "light"


class ResolveWorkspaceBrandUseCase(BrandResolutionPort):
    def __init__(
        self,
        store: WorkspaceThemeStorePort,
        resolution_service: BrandResolutionService,
        color_space: ColorSpacePort,
        font_catalog: FontCatalogPort,
        ui_accent_service: UiAccentDerivationService,
    ) -> None:
        self._store = store
        self._service = resolution_service
        self._cs = color_space
        self._fonts = font_catalog
        self._ui_accent = ui_accent_service

    def resolve(self, workspace_id: UUID, output_shape: BrandOutputShape = BrandOutputShape.CSS) -> dict:
        stored = self._store.find_by_workspace(workspace_id)

        seed_hex = stored.brand_seed.strip() if stored and stored.brand_seed else ""
        if seed_hex:
            token_set = self._service.resolve(BrandSeed(primary=seed_hex, secondary=stored.secondary_seed or None))
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
            "ui_accent": self._ui_accent_payload(seed_hex, output_shape),
        }

    def _ui_accent_payload(self, seed_hex: str, shape: BrandOutputShape) -> dict | None:
        """The brand accent made legible on the app's own surfaces, per theme.

        ``None`` when the workspace has not branded — the app then keeps its
        built-in accent tokens untouched, so an unbranded workspace renders
        exactly as it does today.

        ``brand.primary`` (inside ``light``/``dark``) remains the brand FILL and
        is unchanged; this key is the brand as a *foreground* on our canvas,
        which nothing guaranteed before. Splitting ``text`` from ``decorative``
        keeps the raw colour on brand-carrying chrome (WCAG 1.4.11, 3:1) while
        anything that renders text or state uses the AA-guaranteed variant.
        """
        if not seed_hex:
            return None

        payload: dict = {"source": self._cs.normalize_hex(seed_hex)}
        for palette in APP_SURFACE_PALETTES:
            derived = self._ui_accent.derive(seed_hex, palette)
            payload[palette.key] = {
                "text": self._value(derived.text, shape),
                "decorative": self._value(derived.decorative, shape),
                "adjusted": derived.adjusted,
                # Rounded so the payload is stable/diffable; the guarantee is
                # the >= comparison in the derivation, not this reported number.
                "text_contrast": round(derived.text_ratio, 2),
                "decorative_contrast": round(derived.decorative_ratio, 2),
            }
        return payload

    def _value(self, hex_color: str, shape: BrandOutputShape) -> str:
        if shape == BrandOutputShape.CSS:
            return self._cs.to_channels(hex_color)
        return self._cs.normalize_hex(hex_color)

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
            formatted[key] = radius if key == "radius" else self._value(value, shape)
        return formatted
