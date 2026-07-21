"""Brand-voice adapter — the agents ``BrandVoicePort`` implementation.

The wanjala brand kit (``WorkspaceTheme`` + ``WorkspaceThemeProvider``) was NOT
ported into this fork: the workspace context here has no theme model,
repository, provider, or write surface, so no workspace can ever carry a brand
voice. This adapter therefore returns the empty voice deterministically —
keeping the port satisfied for the chat/prompt pipeline without attempting an
import that cannot succeed (the old best-effort read logged an ImportError
traceback on every agent run). If a brand kit is ever ported, restore the
``WorkspaceThemeProvider.build_brand_voice_use_case()`` read here.
"""

from __future__ import annotations

_EMPTY = {"tone": "", "guidelines": ""}


class WorkspaceBrandVoiceAdapter:
    """Implements the agents ``BrandVoicePort``; voiceless in this fork."""

    def get(self, workspace_id: str) -> dict:
        return dict(_EMPTY)
