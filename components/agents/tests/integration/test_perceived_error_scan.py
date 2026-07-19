"""SEE-205 — the perceived-error scan surfaces flagged conversations as findings.

Seeds real conversations; the Agents-board setup and the finding-persistence are
mocked at their source so the test targets the scan orchestration (which
conversations get flagged, that a finding is emitted per flagged conversation,
and that clean conversations emit nothing) rather than the board machinery.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from components.agents.infrastructure.services.perceived_error_scan import (
    scan_workspace_for_perceived_errors,
)
from infrastructure.persistence.ai.conversations.models import (
    Conversation,
    ConversationMessage,
)


class _FakeEmbeddings:
    def embed_documents(self, texts):
        return [[0.0] * 1536 for _ in texts]

    def embed_query(self, text):
        return [0.0] * 1536


@pytest.fixture(autouse=True)
def _stub_embeddings():
    # workspace_factory's eager reindex signal would otherwise call OpenAI.
    with patch(
        "components.knowledge.infrastructure.factories.embeddings.factory."
        "EmbeddingsFactory.create_embeddings",
        return_value=_FakeEmbeddings(),
    ):
        yield


def _seed_conversation(workspace, turns):
    conversation = Conversation.objects.create(
        user=workspace.workspace_owner, metadata={"workspace_id": str(workspace.id)}
    )
    for role, content in turns:
        ConversationMessage.objects.create(conversation=conversation, role=role, content=content)
    return conversation


class _BoardSetup:
    """Patches the board-setup facades + the finding sink for one test."""

    def __init__(self):
        self.persist = MagicMock(return_value="task-id")

    def __enter__(self):
        board = SimpleNamespace(
            column=lambda _key: "suggested-column",
            team=SimpleNamespace(created_by_id=uuid4()),
        )
        self._patches = [
            patch(
                "components.agents.application.facades.agent_permissions_facade.ensure_ai_identity",
                return_value=(None, SimpleNamespace(id=uuid4())),
            ),
            patch(
                "components.agents.application.facades.agent_permissions_facade.ensure_agents_team",
                return_value=None,
            ),
            patch(
                "components.agents.application.facades.ai_teammate_facade.ensure_agents_board",
                return_value=board,
            ),
            patch(
                "components.agents.application.handlers.specialist_persistence_service.persist_finding_as_task",
                self.persist,
            ),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


@pytest.mark.django_db
class TestPerceivedErrorScan:
    def test_flagged_conversation_emits_one_finding(self, workspace_factory):
        workspace = workspace_factory()
        conversation = _seed_conversation(
            workspace,
            [
                ("user", "What's our donor total?"),
                ("assistant", "It is $500."),
                ("user", "That's wrong, it's $5,000."),
            ],
        )

        with _BoardSetup() as setup:
            created = scan_workspace_for_perceived_errors(str(workspace.id))

        assert created == 1
        assert setup.persist.call_count == 1
        payload = setup.persist.call_args.kwargs["payload_data"]
        assert payload["conversation_id"] == str(conversation.id)

    def test_clean_conversation_emits_nothing(self, workspace_factory):
        workspace = workspace_factory()
        _seed_conversation(
            workspace,
            [
                ("user", "What's our donor total?"),
                ("assistant", "It is $5,000."),
                ("user", "Perfect, thanks!"),
            ],
        )

        with _BoardSetup() as setup:
            created = scan_workspace_for_perceived_errors(str(workspace.id))

        assert created == 0
        assert setup.persist.call_count == 0
