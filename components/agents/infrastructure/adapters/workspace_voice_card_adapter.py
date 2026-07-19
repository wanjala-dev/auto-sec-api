"""Voice style-card adapter (SEE-172, brand-kit edition).

Renders the workspace's voice into a prompt *style card* for the grounded
interactive-draft use case. Since the brand-kit expansion the canonical voice
(tone + written guidelines) lives on the brand kit (``WorkspaceTheme``); the
AI-profile fields that remain on ``WorkspaceAIConfig`` (beneficiary language
rules, prompt addendum) are layered into the same card — one combined voice
source steers chat, drafts, and newsletters alike.

Duck-typed to the use case's ``voice_profile_port`` contract
(``.style_card(workspace_id) -> str``). Best-effort: any miss/failure yields
``""`` so a voice lookup never breaks drafting.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class WorkspaceVoiceCardAdapter:
    """Combine the brand kit's canonical voice with the AI profile's
    language rules into a single style card."""

    def __init__(self, *, config_port: Any, brand_voice_port: Any = None) -> None:
        self._config_port = config_port
        self._brand_voice_port = brand_voice_port

    def _brand_voice(self, workspace_id: str) -> dict:
        if self._brand_voice_port is None:
            return {}
        try:
            return self._brand_voice_port.get(str(workspace_id)) or {}
        except Exception:  # noqa: BLE001 — voice steering is best-effort
            logger.exception(
                "voice_card.brand_voice_load_failed workspace_id=%s", workspace_id
            )
            return {}

    def style_card(self, *, workspace_id: str) -> str:
        if not workspace_id:
            return ""

        voice = self._brand_voice(workspace_id)
        tone = str(voice.get("tone") or "").strip()
        guidelines = str(voice.get("guidelines") or "").strip()

        rules = ""
        addendum = ""
        try:
            config = self._config_port.load(str(workspace_id))
        except Exception:  # noqa: BLE001 — voice steering is best-effort
            logger.exception(
                "voice_card.config_load_failed workspace_id=%s", workspace_id
            )
            config = None
        if config is not None:
            rules = (getattr(config, "beneficiary_language_rules", "") or "").strip()
            addendum = (getattr(config, "custom_system_prompt_addendum", "") or "").strip()

        if not (tone or guidelines or rules or addendum):
            return ""

        lines = [
            "VOICE & STYLE PROFILE (apply to HOW the copy reads — these are "
            "style rules, NOT facts; never invent specifics to satisfy them):"
        ]
        if tone:
            lines.append(f"- Tone: {tone}")
        if guidelines:
            lines.append(f"- Brand voice guidelines: {guidelines}")
        if rules:
            lines.append(f"- Language rules for the people served: {rules}")
        if addendum:
            lines.append(f"- House style: {addendum}")
        return "\n".join(lines) + "\n"
