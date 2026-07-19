"""Unit tests: voice style card adapter (SEE-172, brand-kit edition).

The canonical voice (tone + guidelines) lives on the brand kit
(``WorkspaceTheme``) and reaches the adapter via a ``BrandVoicePort``;
``WorkspaceAIConfig`` contributes only the language rules + prompt addendum.
One combined card steers chat, drafts, and newsletters. Pure logic; no DB.
"""

from __future__ import annotations

import pytest

from components.agents.domain.value_objects.workspace_ai_config import WorkspaceAIConfig
from components.agents.infrastructure.adapters.workspace_voice_card_adapter import (
    WorkspaceVoiceCardAdapter,
)

pytestmark = pytest.mark.unit


class _FakeConfigPort:
    def __init__(self, config):
        self._config = config

    def load(self, workspace_id):
        return self._config


class _FakeBrandVoice:
    def __init__(self, tone="", guidelines=""):
        self._voice = {"tone": tone, "guidelines": guidelines}

    def get(self, workspace_id):
        return dict(self._voice)


class TestWorkspaceVoiceCardAdapter:
    def test_empty_everything_renders_no_card(self):
        adapter = WorkspaceVoiceCardAdapter(
            config_port=_FakeConfigPort(WorkspaceAIConfig()),
            brand_voice_port=_FakeBrandVoice(),
        )
        assert adapter.style_card(workspace_id="w1") == ""

    def test_renders_brand_voice_plus_ai_profile_rules(self):
        adapter = WorkspaceVoiceCardAdapter(
            config_port=_FakeConfigPort(
                WorkspaceAIConfig(
                    beneficiary_language_rules="say 'recipient', never 'child'",
                    custom_system_prompt_addendum="Lead with impact; thank specifically.",
                )
            ),
            brand_voice_port=_FakeBrandVoice(
                tone="warm", guidelines="Short sentences. Always name the program."
            ),
        )
        card = adapter.style_card(workspace_id="w1")
        assert "VOICE & STYLE PROFILE" in card
        assert "Tone: warm" in card
        assert "Short sentences. Always name the program." in card
        assert "say 'recipient', never 'child'" in card
        assert "Lead with impact" in card
        assert "style rules, NOT facts" in card

    def test_tone_comes_from_brand_kit_not_ai_config(self):
        # The legacy WorkspaceAIConfig.voice_tone is no longer a voice source —
        # the brand kit is canonical (the data migration moved values across).
        adapter = WorkspaceVoiceCardAdapter(
            config_port=_FakeConfigPort(WorkspaceAIConfig(voice_tone="activist")),
            brand_voice_port=_FakeBrandVoice(tone="formal"),
        )
        card = adapter.style_card(workspace_id="w1")
        assert "Tone: formal" in card
        assert "activist" not in card

    def test_partial_voice_renders_only_present_fields(self):
        adapter = WorkspaceVoiceCardAdapter(
            config_port=_FakeConfigPort(WorkspaceAIConfig()),
            brand_voice_port=_FakeBrandVoice(tone="formal"),
        )
        card = adapter.style_card(workspace_id="w1")
        assert "Tone: formal" in card
        assert "Language rules" not in card
        assert "House style" not in card

    def test_empty_workspace_id_returns_blank(self):
        adapter = WorkspaceVoiceCardAdapter(
            config_port=_FakeConfigPort(WorkspaceAIConfig()),
            brand_voice_port=_FakeBrandVoice(tone="warm"),
        )
        assert adapter.style_card(workspace_id="") == ""

    def test_config_load_failure_still_renders_brand_voice(self):
        class _Boom:
            def load(self, workspace_id):
                raise RuntimeError("config store down")

        adapter = WorkspaceVoiceCardAdapter(
            config_port=_Boom(), brand_voice_port=_FakeBrandVoice(tone="warm")
        )
        card = adapter.style_card(workspace_id="w1")
        assert "Tone: warm" in card

    def test_brand_voice_failure_still_renders_ai_profile_rules(self):
        class _BoomVoice:
            def get(self, workspace_id):
                raise RuntimeError("theme store down")

        adapter = WorkspaceVoiceCardAdapter(
            config_port=_FakeConfigPort(
                WorkspaceAIConfig(beneficiary_language_rules="say recipient")
            ),
            brand_voice_port=_BoomVoice(),
        )
        card = adapter.style_card(workspace_id="w1")
        assert "say recipient" in card

    def test_no_brand_voice_port_degrades_to_rules_only(self):
        adapter = WorkspaceVoiceCardAdapter(
            config_port=_FakeConfigPort(
                WorkspaceAIConfig(beneficiary_language_rules="say recipient")
            ),
        )
        card = adapter.style_card(workspace_id="w1")
        assert "say recipient" in card
        assert "Tone:" not in card
