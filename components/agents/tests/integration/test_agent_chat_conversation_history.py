"""The planner must see prior conversation turns.

2026-05-08 incident shape: Henry asked "how many tasks do we have?",
got a real answer, then followed up with "who is assigned to those 4
tasks?" and got "Deep agent finished without producing a response."
The planner was stateless across turns — Turn 2's goal arrived with
no Turn 1 context, so "those 4 tasks" was unresolvable.

This file exercises the use case end-to-end against the real DB but
with the deep-run port stubbed so we can assert exactly what context
the planner would have seen.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from components.agents.application.commands.agent_chat_command import AgentChatCommand
from components.agents.application.commands.deep_run_command import (
    DeepPlanAndRunCommand,
    DeepRunSuccess,
)
from components.agents.application.use_cases.agent_chat_use_case import (
    AgentChatUseCase,
    _load_conversation_history,
)


class _FakePolicyDecision:
    def __init__(self, allowed: bool, reason: str = ""):
        self.is_allowed = allowed
        self.reason = reason


def _build_use_case(deep_result):
    deep = MagicMock()
    deep.execute = MagicMock(return_value=deep_result)
    entitlement = MagicMock()
    entitlement.is_agent_enabled_for_workspace = MagicMock(return_value=True)
    ai_config_port = MagicMock()
    ai_config_port.load = MagicMock(
        return_value=type("AIConfig", (), {"ai_enabled": True})()
    )
    ai_config_port.get_messages_used_today = MagicMock(return_value=0)

    use_case = AgentChatUseCase(
        deep_plan_and_run=deep,
        entitlement=entitlement,
        ai_config_port=ai_config_port,
        session_memory=None,
    )

    from components.agents.application.use_cases import agent_chat_use_case as mod

    mod._persona_policy.check_feature_access = MagicMock(
        return_value=_FakePolicyDecision(True)
    )
    mod._persona_policy.check_agent_access = MagicMock(
        return_value=_FakePolicyDecision(True)
    )
    return use_case, deep


@pytest.mark.django_db
class TestLoadConversationHistory:
    """Direct test of the helper — pin the data shape the planner sees."""

    def _seed_conversation(self, user, exchanges):
        """``exchanges`` = [(role, content), ...] in chronological order."""
        from infrastructure.persistence.ai.conversations.models import (
            Conversation,
            ConversationMessage,
        )

        conv = Conversation.objects.create(user_id=user.id, title="t")
        for role, content in exchanges:
            ConversationMessage.objects.create(
                conversation=conv, role=role, content=content
            )
        return str(conv.id)

    def test_returns_empty_when_no_conversation_id(self):
        assert _load_conversation_history(None) == []
        assert _load_conversation_history("") == []

    def test_returns_empty_when_conversation_is_empty(self, user_factory):
        from infrastructure.persistence.ai.conversations.models import Conversation

        u = user_factory()
        conv = Conversation.objects.create(user_id=u.id, title="empty")
        assert _load_conversation_history(str(conv.id)) == []

    def test_returns_messages_in_chronological_order(self, user_factory):
        u = user_factory()
        conv_id = self._seed_conversation(
            u,
            [
                ("human", "how many tasks?"),
                ("assistant", "you have 4 todo tasks: A, B, C, D"),
                ("human", "who is assigned?"),
            ],
        )
        history = _load_conversation_history(conv_id)
        assert [h["role"] for h in history] == ["human", "assistant", "human"]
        assert "4 todo tasks" in history[1]["content"]

    def test_caps_at_recent_turns(self, user_factory):
        u = user_factory()
        # Seed 25 turns; helper should keep only the most recent 10.
        exchanges = [("human", f"q{i}") for i in range(25)]
        conv_id = self._seed_conversation(u, exchanges)
        history = _load_conversation_history(conv_id)
        assert len(history) == 10
        # The 10 most recent are q15..q24.
        assert history[0]["content"] == "q15"
        assert history[-1]["content"] == "q24"

    def test_truncates_long_messages(self, user_factory):
        u = user_factory()
        very_long = "x" * 5000
        conv_id = self._seed_conversation(u, [("assistant", very_long)])
        history = _load_conversation_history(conv_id)
        assert len(history[0]["content"]) <= 801, (
            "Long messages must be truncated so the planner's prompt "
            "doesn't blow its token budget."
        )
        assert history[0]["content"].endswith("…")

    def test_skips_empty_content_rows(self, user_factory):
        u = user_factory()
        conv_id = self._seed_conversation(
            u,
            [
                ("human", "real"),
                ("assistant", ""),
                ("assistant", "   "),
                ("human", "another"),
            ],
        )
        history = _load_conversation_history(conv_id)
        assert [h["content"] for h in history] == ["real", "another"]


@pytest.mark.django_db
class TestUseCaseThreadsHistoryToPlanner:
    """End-to-end assertion: the use case loads the prior turns and
    threads them onto ``DeepPlanAndRunCommand.extra_context`` BEFORE
    persisting the new user message (so the new message doesn't end
    up in its own context).
    """

    def test_followup_turn_carries_prior_messages_in_extra_context(
        self, user_factory, workspace_factory
    ):
        from infrastructure.persistence.ai.conversations.models import (
            Conversation,
            ConversationMessage,
        )

        owner = user_factory()
        ws = workspace_factory(owner=owner)
        conv = Conversation.objects.create(user_id=owner.id, title="chat")
        # Turn 1 already happened.
        ConversationMessage.objects.create(
            conversation=conv, role="human", content="how many tasks?"
        )
        ConversationMessage.objects.create(
            conversation=conv,
            role="assistant",
            content="You have 4 todo tasks: A, B, C, D",
        )

        use_case, deep = _build_use_case(
            DeepRunSuccess(
                plan_id="p-1",
                state={"final_output": {"answer": "stub"}},
            )
        )

        # Turn 2: follow-up referring back to "those tasks".
        result = use_case.execute(
            AgentChatCommand(
                query="who is assigned to those 4 tasks?",
                workspace_id=ws.id,
                user_id=owner.id,
                conversation_id=conv.id,
                agent_type="workspace_agent",
            )
        )
        assert result is not None

        # The deep-run command the planner sees should carry the
        # prior turns under ``extra_context.conversation_history``.
        deep_command: DeepPlanAndRunCommand = deep.execute.call_args.args[0]
        assert deep_command.extra_context is not None, (
            "extra_context must be populated on follow-up turns. "
            "Without it the planner is stateless and can't resolve "
            "cross-turn references like 'those 4 tasks'."
        )
        history = deep_command.extra_context.get("conversation_history")
        assert isinstance(history, list)
        assert len(history) == 2
        assert history[0]["role"] == "human"
        assert "how many tasks" in history[0]["content"]
        assert history[1]["role"] == "assistant"
        assert "4 todo tasks" in history[1]["content"]
        # The current user query (Turn 2) must NOT be in history —
        # it's the goal, not context.
        assert all(
            "who is assigned" not in h["content"] for h in history
        ), (
            "The current goal must not appear in conversation_history; "
            "it would double-count and confuse the planner."
        )

    def test_first_turn_has_empty_extra_context(
        self, user_factory, workspace_factory
    ):
        """Brand-new conversation — no prior turns, no extra_context
        carrying conversation_history. The use case sets
        ``extra_context=None`` so the planner doesn't see an empty
        dict it has to interpret.
        """
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        use_case, deep = _build_use_case(
            DeepRunSuccess(
                plan_id="p-1", state={"final_output": {"answer": "stub"}}
            )
        )

        use_case.execute(
            AgentChatCommand(
                query="hello",
                workspace_id=ws.id,
                user_id=owner.id,
                agent_type="workspace_agent",
                # No conversation_id — first turn.
            )
        )
        deep_command = deep.execute.call_args.args[0]
        assert (
            deep_command.extra_context is None
            or not deep_command.extra_context.get("conversation_history")
        ), "First turn must not pretend it has history."
