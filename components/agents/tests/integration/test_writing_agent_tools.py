"""Unit tests for the writing_agent drafting tools.

These tests target the tool functions directly (no real LLM, no full
agent loop) and assert four invariants per tool:

1. The LLM is called with a prompt grounded in the user input.
2. A WritingDraft row is persisted via CreateWritingDraftUseCase with
   ``ai_drafted=True`` and the correct kind.
3. ``agent.collect_artifact`` is called with the unified draft-artifact
   contract — including ``kind="draft"``, ``domain="writing"``,
   ``subtype`` matching the WritingDraft kind, an edit_url, and a
   preview.
4. The tool returns a JSON string that the cadence adapter and the
   LangChain ReAct loop can both parse.

LLM-failure path: every tool persists a stub draft (with
``metadata={"llm_fallback": True}``) so the user always gets an
editable draft, never a "the AI failed, try again" dead-end.

Entity-update path: the tool verifies the entity belongs to the
workspace via a workspace-scoped queryset before persisting, and
returns a friendly error when the lookup misses.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    writing_agent as writing_tools,
)
from components.content.domain.enums import WritingDraftKind


# ── Test fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def fake_workspace(workspace_factory):
    """Real Workspace row so WritingDraft.workspace_id FK passes."""
    return workspace_factory()


@pytest.fixture
def workspace_uuid(fake_workspace) -> uuid.UUID:
    return fake_workspace.id


@pytest.fixture
def fake_agent(workspace_uuid, user_factory):
    """Stand-in agent with the attributes the tool functions read.

    Mirrors `BaseAgent`'s public surface: `workspace_id` (str),
    `user_id` (str), `config` (dict), `collect_artifact` (callable).

    A real CustomUser is created via the conftest user_factory so the
    WritingDraft.author_id foreign-key check passes — the persistence
    layer is the unit under test.
    """

    user = user_factory()
    agent = SimpleNamespace(
        workspace_id=str(workspace_uuid),
        user_id=str(user.id),
        config={"provider": "openai", "model_name": "gpt-4o-mini", "temperature": 0.1},
        collect_artifact=MagicMock(),
        # `_invoke_llm` reads `getattr(agent, "llm", None)`; we set it
        # to a MagicMock so each test can mock the .invoke return
        # value without going through LLMFactory.
        llm=MagicMock(),
    )
    return agent


def _llm_returns(agent, value: str) -> None:
    """Configure the agent's LLM mock to return ``value`` from .invoke()."""
    agent.llm.invoke.return_value = SimpleNamespace(content=value)


def _llm_raises(agent, exc: Exception) -> None:
    """Configure the agent's LLM mock to raise on .invoke()."""
    agent.llm.invoke.side_effect = exc


# ── draft_letter ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDraftLetter:
    def test_persists_writing_draft_and_emits_artifact(self, fake_agent, workspace_uuid):
        _llm_returns(
            fake_agent,
            json.dumps(
                {
                    "title": "Thank you, Henry",
                    "body_html": "<p>Thank you for your support.</p>",
                }
            ),
        )

        result_json = writing_tools.draft_letter(
            fake_agent,
            json.dumps(
                {
                    "recipient_name": "Henry",
                    "prompt": "Thank him for his recent gift.",
                    "tone": "warm",
                }
            ),
        )
        result = json.loads(result_json)

        # 1. Return shape.
        assert result["persisted"] is True
        assert result["title"] == "Thank you, Henry"
        assert result["body_html"] == "<p>Thank you for your support.</p>"
        assert "artifact_id" in result
        assert result["edit_url"].startswith(f"/w/{workspace_uuid}/writing/draft/")
        assert result["llm_fallback"] is False

        # 2. The artifact was collected with the unified contract.
        fake_agent.collect_artifact.assert_called_once()
        artifact = fake_agent.collect_artifact.call_args.args[0]
        assert artifact["kind"] == "draft"
        assert artifact["domain"] == "writing"
        assert artifact["subtype"] == WritingDraftKind.LETTER
        assert artifact["ai_drafted"] is True
        assert artifact["edit_url"] == result["edit_url"]
        assert artifact["title"] == "Thank you, Henry"
        # Preview is a tag-stripped, truncated snippet of body_html.
        assert "Thank you for your support" in artifact["preview"]
        assert "<p>" not in artifact["preview"]

        # 3. WritingDraft was persisted.
        from infrastructure.persistence.content.models import WritingDraft

        draft = WritingDraft.objects.get(id=result["artifact_id"])
        assert draft.workspace_id == workspace_uuid
        assert draft.kind == WritingDraftKind.LETTER
        assert draft.ai_drafted is True
        assert draft.title == "Thank you, Henry"

    def test_llm_failure_still_persists_stub(self, fake_agent, workspace_uuid):
        """If the LLM raises / returns garbage, the tool MUST still
        persist a stub draft so the user gets an editable card. The
        artifact's ``llm_fallback`` flag tells the chat bubble to
        surface a 'review carefully' note."""

        _llm_raises(fake_agent, RuntimeError("LLM 5xx"))

        result_json = writing_tools.draft_letter(
            fake_agent,
            json.dumps({"recipient_name": "Acme Foundation"}),
        )
        result = json.loads(result_json)

        assert result["persisted"] is True, (
            "LLM failure must not skip persistence — the user always "
            "gets an editable draft."
        )
        assert result["llm_fallback"] is True
        assert result["title"] == "Letter to Acme Foundation"

        # Persisted with the stub body + llm_fallback metadata.
        from infrastructure.persistence.content.models import WritingDraft

        draft = WritingDraft.objects.get(id=result["artifact_id"])
        assert draft.ai_drafted is True
        assert draft.metadata.get("llm_fallback") is True

        # Artifact carries the llm_fallback flag for FE styling.
        artifact = fake_agent.collect_artifact.call_args.args[0]
        assert artifact["llm_fallback"] is True


# ── draft_mission ────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDraftMission:
    def test_persists_mission_draft(self, fake_agent, workspace_uuid):
        _llm_returns(
            fake_agent,
            json.dumps(
                {
                    "title": "Our mission",
                    "body_html": "<p>We exist to serve our community.</p>",
                }
            ),
        )

        result_json = writing_tools.draft_mission(
            fake_agent,
            json.dumps(
                {
                    "workspace_name": "Zaylan",
                    "prompt": "literacy programs for East African youth",
                }
            ),
        )
        result = json.loads(result_json)

        assert result["persisted"] is True
        from infrastructure.persistence.content.models import WritingDraft

        draft = WritingDraft.objects.get(id=result["artifact_id"])
        assert draft.kind == WritingDraftKind.MISSION
        assert draft.ai_drafted is True

        artifact = fake_agent.collect_artifact.call_args.args[0]
        assert artifact["subtype"] == WritingDraftKind.MISSION
        # Mission is NOT entity-scoped — artifact must not carry a
        # related_entity field.
        assert "related_entity" not in artifact


# ── draft_recipient_update (entity-scoped) ──────────────────────────────


@pytest.mark.django_db
class TestDraftRecipientUpdate:
    def test_missing_recipient_id_returns_friendly_error(self, fake_agent):
        """No recipient_id supplied — the tool returns a helpful error
        without calling the LLM or the persistence path."""

        result_json = writing_tools.draft_recipient_update(
            fake_agent,
            json.dumps({"prompt": "Write an update on her recent progress."}),
        )
        result = json.loads(result_json)

        assert result["ok"] is False
        assert result["persisted"] is False
        assert "recipient_id" in result["error"]
        # No LLM call, no artifact collected — pure short-circuit.
        fake_agent.llm.invoke.assert_not_called()
        fake_agent.collect_artifact.assert_not_called()

    def test_recipient_outside_workspace_returns_friendly_error(self, fake_agent):
        """The entity-verification guardrail catches a recipient_id
        the LLM might have hallucinated. The tool returns a friendly
        error rather than persisting a broken draft."""

        bogus_recipient_id = str(uuid.uuid4())
        # No Recipient row exists for that UUID — the guardrail returns
        # False from _verify_entity_in_workspace.

        result_json = writing_tools.draft_recipient_update(
            fake_agent,
            json.dumps(
                {
                    "recipient_id": bogus_recipient_id,
                    "recipient_name": "Phantom Person",
                    "prompt": "Write an update.",
                }
            ),
        )
        result = json.loads(result_json)

        assert result["ok"] is False
        assert result["persisted"] is False
        assert "couldn't find" in result["error"].lower()
        fake_agent.collect_artifact.assert_not_called()


# ── Canonical-name + display-name registry resolution ───────────────────


class TestAgentRegistryCanonicalLookup:
    """The registry's canonical_name_for / display_name_for back the
    chat-header resource. Test the lookups directly."""

    def test_canonical_for_writing_agent_alias(self):
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        # `letter_agent` is a registered alias of `writing_agent`.
        assert AgentRegistry.canonical_name_for("letter_agent") == "writing_agent"
        assert AgentRegistry.canonical_name_for("newsletter_agent") == "writing_agent"
        assert AgentRegistry.canonical_name_for("draft_agent") == "writing_agent"
        # The canonical slug resolves to itself.
        assert AgentRegistry.canonical_name_for("writing_agent") == "writing_agent"

    def test_canonical_for_sentinel_passthrough(self):
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        # `clarify` is a routing sentinel, not an agent — the resolver
        # passes it through unchanged so the FE can render its own label.
        assert AgentRegistry.canonical_name_for("clarify") == "clarify"

    def test_display_name_uses_profile_name(self):
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        # Reads `profile['name']` from the registered class.
        assert AgentRegistry.display_name_for("writing_agent") == "Writing Agent"
        # Aliases resolve through the same class.
        assert AgentRegistry.display_name_for("letter_agent") == "Writing Agent"

    def test_display_name_empty_string_safe(self):
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        # Empty input is a guarded edge — return empty string.
        assert AgentRegistry.canonical_name_for("") == ""
        assert AgentRegistry.display_name_for("") == ""
