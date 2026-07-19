"""Brand-voice adapter — reads the canonical voice from the workspace
context's brand kit (``WorkspaceTheme``) via its published provider.

Same seam pattern as ``pdf_brand_assets.resolve_brand_colors``: a lazy
cross-context call at the infrastructure layer, degraded to blank on any
failure — voice is decoration and must never fail a newsletter draft.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_EMPTY = {"tone": "", "guidelines": ""}


class WorkspaceBrandVoiceAdapter:
    """Implements the content ``BrandVoicePort`` against the workspace context."""

    def get(self, workspace_id: str) -> dict:
        if not workspace_id:
            return dict(_EMPTY)
        try:
            from components.workspace.application.providers.workspace_theme_provider import (
                WorkspaceThemeProvider,
            )

            voice = WorkspaceThemeProvider.build_brand_voice_use_case().execute(workspace_id)
            return {
                "tone": str(voice.get("tone") or ""),
                "guidelines": str(voice.get("guidelines") or ""),
            }
        except Exception:  # noqa: BLE001 — voice steering is best-effort
            logger.exception("newsletter_brand_voice.load_failed workspace_id=%s", workspace_id)
            return dict(_EMPTY)
