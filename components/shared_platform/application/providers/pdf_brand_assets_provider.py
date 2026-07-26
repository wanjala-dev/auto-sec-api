"""Published seam for shared PDF brand-asset resolution.

Resolving a workspace's brand colours for PDF letterheads lives in shared_platform
infrastructure. Contexts that render branded PDFs (content writing) reach it through
this application-layer re-export instead of importing ``shared_platform
.infrastructure.services.pdf_brand_assets`` directly (ADR 0004 infra-boundary series).
"""

from __future__ import annotations

from components.shared_platform.infrastructure.services.pdf_brand_assets import (
    DEFAULT_BRAND_DATA_URI,
    resolve_brand_colors,
)

__all__ = ["DEFAULT_BRAND_DATA_URI", "resolve_brand_colors"]
