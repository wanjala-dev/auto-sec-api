"""Repository: BrandFontOption catalog reads (implements FontCatalogPort)."""

from __future__ import annotations

from components.workspace.application.ports.font_catalog_port import FontCatalogPort, FontOption


def _to_option(model) -> FontOption:
    return FontOption(
        key=model.key,
        label=model.label,
        category=model.category,
        css_stack=model.css_stack,
        google_family=model.google_family or "",
        sort_order=model.sort_order,
    )


class BrandFontCatalogRepository(FontCatalogPort):
    def list_active(self) -> list[FontOption]:
        from infrastructure.persistence.workspaces.theming.models import BrandFontOption

        return [_to_option(obj) for obj in BrandFontOption.objects.filter(active=True)]

    def find_by_key(self, key: str) -> FontOption | None:
        from infrastructure.persistence.workspaces.theming.models import BrandFontOption

        obj = BrandFontOption.objects.filter(key=key, active=True).first()
        return _to_option(obj) if obj else None
