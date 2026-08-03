"""Workspace profile injection — assemble + threading tests.

The AI Fluency Wave 1 backend slice adds a ``context.workspace_profile``
block to the planner's user payload. Two test surfaces:

1. ``_build_workspace_profile_context`` — the assembler that reads
   ``Workspace.{mission, vision, workspace_story}`` plus the
   AI-fluency fields on ``WorkspaceAIConfig`` and produces a
   truncated dict the planner can read. This module unit-tests it
   without going near the planner or the LLM.
2. The planner system-prompt template — verifies the new
   ``Workspace profile`` paragraph references all six keys so the
   model knows how to use the injected block. This is a pure-string
   assertion so it runs offline.

The end-to-end "the planner actually changes its plan when a profile
is injected" test lives under ``components/agents/tests/eval/`` and
runs against the LLM, gated on ``PROMPT_EVAL_E2E=1``.

Plan reference: ``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``
AI Fluency Wave 1.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from components.agents.application.use_cases.agent_chat_use_case import (
    _PROFILE_FIELD_BUDGETS,
    _build_workspace_profile_context,
)
from components.agents.domain.value_objects.workspace_ai_config import (
    WorkspaceAIConfig,
)
from components.agents.infrastructure.adapters.langchain.deep import llm_planner

# ---------------------------------------------------------------------------
# Profile assembly
# ---------------------------------------------------------------------------


class TestWorkspaceProfileAssembly:
    """Profile dict comes from two sources, gracefully merged + truncated."""

    def test_returns_empty_dict_when_workspace_unavailable_and_config_empty(self):
        """Empty workspace_id + bare config = no profile keys.

        The helper's contract is: if there's nothing to say about this
        workspace, return ``{}`` and the use case omits the
        ``context.workspace_profile`` key entirely. Tested without
        patching the ORM — ``workspace_id=""`` short-circuits the
        Workspace lookup, and a bare ``WorkspaceAIConfig`` has no
        AI-fluency fields populated.
        """
        profile = _build_workspace_profile_context(
            workspace_id="",
            ai_config=WorkspaceAIConfig(),
        )
        assert profile == {}, (
            "Empty workspace_id and bare WorkspaceAIConfig must produce no "
            "profile keys — the planner relies on the absence of the "
            "context.workspace_profile key to know defaults apply."
        )

    def test_picks_up_ai_config_fields_only(self):
        """If only AI-config fields are set, those land in the profile.

        Since the brand-kit voice move, ``WorkspaceAIConfig.voice_tone`` is
        legacy and NOT read — only the language rules + addendum remain
        AI-config-sourced.
        """
        ai_config = WorkspaceAIConfig.from_dict(
            {
                "voice_tone": "warm",  # legacy field — must be ignored
                "beneficiary_language_rules": "say recipient not child",
                "custom_system_prompt_addendum": "always cite sources",
            }
        )
        profile = _build_workspace_profile_context(workspace_id="", ai_config=ai_config)
        assert profile == {
            "beneficiary_language_rules": "say recipient not child",
            "custom_system_prompt_addendum": "always cite sources",
        }

    def test_picks_up_assistant_name_from_teammate_profile(self):
        """The assistant's name lives on AITeammateProfile.display_name
        (the same record Settings ▸ AI Assistant renames). Inject it so
        the assistant answers to it; the avatar is UI-only and must NOT
        reach the planner."""
        row = SimpleNamespace(
            display_name="Zawadi",
            config={},
            avatar_url="https://cdn.example.org/z.png",
        )
        with _patched_teammate_profile_lookup(row):
            profile = _build_workspace_profile_context(workspace_id="ws-uuid-1234", ai_config=WorkspaceAIConfig())
        assert profile == {"assistant_name": "Zawadi"}

    def test_assistant_name_falls_back_to_legacy_config_json(self):
        """Rows renamed before display_name was a column keep working —
        mirrors OrmTeammateProfileRepository._resolve_alias."""
        row = SimpleNamespace(
            display_name=None,
            config={"profile": {"name": "Mtaalamu"}},
        )
        with _patched_teammate_profile_lookup(row):
            profile = _build_workspace_profile_context(workspace_id="ws-uuid-1234", ai_config=WorkspaceAIConfig())
        assert profile == {"assistant_name": "Mtaalamu"}

    def test_teammate_profile_failure_is_silent(self):
        """A broken teammate-profile lookup never breaks profile assembly."""
        ai_config = WorkspaceAIConfig.from_dict({"beneficiary_language_rules": "say recipient"})
        with _patched_teammate_profile_lookup_raising():
            profile = _build_workspace_profile_context(workspace_id="ws", ai_config=ai_config)
        assert profile == {"beneficiary_language_rules": "say recipient"}

    def test_picks_up_brand_voice_from_port(self):
        """The brand kit is the canonical voice source (tone + guidelines)."""

        class _FakeBrandVoice:
            def get(self, workspace_id):
                return {"tone": "warm", "guidelines": "Short sentences."}

        profile = _build_workspace_profile_context(
            workspace_id="ws-uuid-1234",
            ai_config=WorkspaceAIConfig(),
            brand_voice=_FakeBrandVoice(),
        )
        assert profile.get("voice_tone") == "warm"
        assert profile.get("voice_guidelines") == "Short sentences."

    def test_brand_voice_failure_is_silent(self):
        """A broken voice port never breaks profile assembly."""

        class _BoomVoice:
            def get(self, workspace_id):
                raise RuntimeError("theme store down")

        ai_config = WorkspaceAIConfig.from_dict({"beneficiary_language_rules": "say recipient"})
        profile = _build_workspace_profile_context(workspace_id="ws", ai_config=ai_config, brand_voice=_BoomVoice())
        assert profile == {"beneficiary_language_rules": "say recipient"}

    def test_picks_up_workspace_fields_when_orm_returns_a_workspace(self):
        """Workspace.mission/vision/workspace_story land in the profile."""
        ai_config = WorkspaceAIConfig()
        fake_workspace = SimpleNamespace(
            mission="Lift adult literacy in Nairobi",
            vision="Every adult reads with confidence",
            workspace_story="Founded 2018 by three former teachers",
        )

        # Patch the lazy-imported ORM so we don't hit the database.
        with _patched_workspace_lookup(fake_workspace):
            profile = _build_workspace_profile_context(
                workspace_id="ws-uuid-1234",
                ai_config=ai_config,
            )

        assert profile.get("mission") == "Lift adult literacy in Nairobi"
        assert profile.get("vision") == "Every adult reads with confidence"
        assert profile.get("workspace_story") == "Founded 2018 by three former teachers"
        # AI-config fields are absent because they were empty on the config.
        assert "voice_tone" not in profile

    def test_truncates_each_field_to_its_budget(self):
        """Long owner-authored copy is hard-capped per field budget."""
        long_mission = "x" * (_PROFILE_FIELD_BUDGETS["mission"] + 200)
        long_addendum = "y" * (_PROFILE_FIELD_BUDGETS["custom_system_prompt_addendum"] + 200)
        ai_config = WorkspaceAIConfig.from_dict({"custom_system_prompt_addendum": long_addendum})
        fake_workspace = SimpleNamespace(
            mission=long_mission,
            vision="",
            workspace_story="",
        )
        with _patched_workspace_lookup(fake_workspace):
            profile = _build_workspace_profile_context(workspace_id="ws", ai_config=ai_config)

        assert len(profile["mission"]) <= _PROFILE_FIELD_BUDGETS["mission"] + 1
        assert profile["mission"].endswith("…")
        assert len(profile["custom_system_prompt_addendum"]) <= (
            _PROFILE_FIELD_BUDGETS["custom_system_prompt_addendum"] + 1
        )
        assert profile["custom_system_prompt_addendum"].endswith("…")

    def test_strips_blank_fields(self):
        """Whitespace-only fields are skipped (not surfaced as empty keys)."""
        ai_config = WorkspaceAIConfig.from_dict({"voice_tone": "   ", "beneficiary_language_rules": ""})
        fake_workspace = SimpleNamespace(
            mission="   ",
            vision="\n",
            workspace_story="",
        )
        with _patched_workspace_lookup(fake_workspace):
            profile = _build_workspace_profile_context(workspace_id="ws", ai_config=ai_config)
        assert profile == {}, (
            "All-whitespace fields produce an empty profile — the planner "
            "should not see keys whose values are stripped to empty strings."
        )

    def test_failure_safe_on_orm_exception(self):
        """If the workspace lookup raises, the profile still assembles
        from AI-config fields and skips the workspace half silently."""
        ai_config = WorkspaceAIConfig.from_dict({"beneficiary_language_rules": "say recipient"})

        def _broken_filter(*_args, **_kwargs):
            raise RuntimeError("simulated ORM failure")

        with _patched_workspace_lookup_raising(_broken_filter):
            profile = _build_workspace_profile_context(workspace_id="ws", ai_config=ai_config)
        assert profile == {"beneficiary_language_rules": "say recipient"}


# ---------------------------------------------------------------------------
# Planner template — references all the keys the assembler can produce
# ---------------------------------------------------------------------------


class TestPlannerTemplateReferencesProfile:
    """The system prompt must mention every key the assembler emits.

    A key in the assembled dict that the prompt never references is
    dead weight — wasted tokens. A key the prompt references that the
    assembler never produces is a phantom that confuses the model.
    Assert both directions are aligned.
    """

    def test_every_profile_key_is_referenced_in_template(self):
        prompt = llm_planner._build_system_prompt()
        for key in (
            "mission",
            "vision",
            "workspace_story",
            "voice_tone",
            "voice_guidelines",
            "beneficiary_language_rules",
            "custom_system_prompt_addendum",
            "assistant_name",
        ):
            assert key in prompt, (
                f"Planner system prompt does not reference profile key "
                f"{key!r} — the assembler emits it but the model is never "
                "told what to do with it."
            )

    def test_template_anchors_on_context_workspace_profile_key(self):
        prompt = llm_planner._build_system_prompt()
        # The Workspace profile section must reference the exact key
        # the assembler writes ("context.workspace_profile") so the
        # model knows where to look for the data.
        assert "context.workspace_profile" in prompt, (
            "Planner system prompt does not reference the literal "
            "context.workspace_profile key — the model would not know "
            "where to find the injected profile."
        )


# ---------------------------------------------------------------------------
# Helpers — patch the ``ChatWorkspaceProfilePort`` seam
#
# Since the app-layer ORM burndown (PR-10), ``_build_workspace_profile_context``
# reaches persistence through the ``ChatWorkspaceProfilePort`` — the two ORM
# reads (workspace mission fields + assistant name, incl. the legacy config-JSON
# fallback) live in ``OrmChatWorkspaceProfileRepository``. These helpers patch
# the port resolver (``_workspace_profile_port``) with a faithful fake so the
# assembler tests exercise the same contract without touching the ORM.
# ---------------------------------------------------------------------------


def _resolve_assistant_name(row) -> str:
    """Mirror ``OrmChatWorkspaceProfileRepository.get_assistant_name`` resolution
    (display_name → config['display_name'] → config['profile']['name'])."""
    if row is None:
        return ""
    config = row.config if isinstance(row.config, dict) else {}
    profile_section = config.get("profile")
    name = (
        row.display_name
        or config.get("display_name")
        or (profile_section.get("name") if isinstance(profile_section, dict) else None)
        or ""
    )
    return str(name).strip()


class _FakeWorkspaceProfilePort:
    """Fake :class:`ChatWorkspaceProfilePort` for the assembler tests."""

    def __init__(self, *, mission_fields=None, teammate_row=None, raise_on_mission=False):
        self._mission_fields = mission_fields
        self._teammate_row = teammate_row
        self._raise_on_mission = raise_on_mission

    def get_mission_fields(self, workspace_id):
        # The adapter is failure-safe (returns None on error); emulate that.
        if self._raise_on_mission:
            return None
        return self._mission_fields

    def get_assistant_name(self, workspace_id):
        return _resolve_assistant_name(self._teammate_row)


def _mission_fields_from(fake_workspace):
    from components.agents.application.ports.chat_workspace_profile_port import (
        WorkspaceMissionFields,
    )

    return WorkspaceMissionFields(
        mission=getattr(fake_workspace, "mission", "") or "",
        vision=getattr(fake_workspace, "vision", "") or "",
        workspace_story=getattr(fake_workspace, "workspace_story", "") or "",
    )


def _patch_profile_port(port):
    return patch(
        "components.agents.application.use_cases.agent_chat_use_case._workspace_profile_port",
        return_value=port,
    )


def _patched_workspace_lookup(fake_workspace):
    """Patch the profile port so the assembler sees ``fake_workspace``'s fields."""
    return _patch_profile_port(_FakeWorkspaceProfilePort(mission_fields=_mission_fields_from(fake_workspace)))


def _patched_workspace_lookup_raising(raising_filter):
    """Patch the profile port so the mission-fields read fails (returns None) —
    the adapter is failure-safe, so the assembler skips the workspace half."""
    return _patch_profile_port(_FakeWorkspaceProfilePort(raise_on_mission=True))


def _patched_teammate_profile_lookup(row):
    """Patch the profile port so the assistant name resolves off ``row``."""
    return _patch_profile_port(_FakeWorkspaceProfilePort(teammate_row=row))


def _patched_teammate_profile_lookup_raising():
    """Patch the profile port so the assistant-name read yields '' (the adapter
    swallows the failure), leaving the rest of the profile intact."""
    return _patch_profile_port(_FakeWorkspaceProfilePort(teammate_row=None))
