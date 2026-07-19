import uuid
from unittest import mock

import pytest

from components.agents.infrastructure.adapters.langchain.base import BaseAgent
from infrastructure.persistence.ai.conversations.models import Conversation


class DummyChatMemory:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.max_messages = None
        self.max_message_chars = None
        self.max_total_chars = None


class DummyMemory:
    def __init__(self, conversation_id: str):
        self.chat_memory = DummyChatMemory(conversation_id)


class DummyMemoryService:
    def __init__(self, conversation_id: str):
        self._conversation_id = conversation_id
        self._memory = DummyMemory(conversation_id)

    def get_memory(self, *args, **kwargs):
        return self._memory

    def get_conversation_id(self):
        return self._conversation_id


class DummyAgent(BaseAgent):
    def _setup_tools(self):
        self.tools = []

    def _setup_agent(self, **_kwargs):
        self._setup_tools()
        self.agent_executor = mock.Mock()


@pytest.mark.django_db
def test_run_context_overrides_conversation_and_limits(monkeypatch, user_factory, workspace_factory):
    workspace = workspace_factory()
    user = user_factory()

    base_conversation_id = str(uuid.uuid4())
    dummy_service = DummyMemoryService(base_conversation_id)

    # ``BaseAgent`` imports ``get_agent_memory_service`` via a from-import
    # in ``components.agents.infrastructure.adapters.langchain.base`` —
    # patch the binding in that module so the substitution survives the
    # constructor call (the legacy
    # ``infrastructure.persistence.ai.agents.base`` import path was
    # removed during the DDD/Hex refactor).
    monkeypatch.setattr(
        "components.agents.infrastructure.adapters.langchain.base.get_agent_memory_service",
        lambda _agent_id: dummy_service,
    )

    agent = DummyAgent(
        agent_id=str(uuid.uuid4()),
        user_id=str(user.id),
        workspace_id=str(workspace.id),
    )

    run_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    agent._apply_run_context(
        {
            "conversation_id": conversation_id,
            "run_id": run_id,
            "plan_id": "plan-1",
            "memory_limits": {
                "max_messages": 3,
                "max_message_chars": 10,
                "max_total_chars": 50,
            },
        }
    )

    conversation = Conversation.objects.get(id=conversation_id)
    assert conversation.user_id == user.id
    assert conversation.metadata["run_id"] == run_id
    assert conversation.metadata["plan_id"] == "plan-1"
    assert str(conversation.metadata["workspace_id"]) == str(workspace.id)

    assert agent.memory.chat_memory.conversation_id == conversation_id
    assert agent.memory.chat_memory.max_messages == 3
    assert agent.memory.chat_memory.max_message_chars == 10
    assert agent.memory.chat_memory.max_total_chars == 50
