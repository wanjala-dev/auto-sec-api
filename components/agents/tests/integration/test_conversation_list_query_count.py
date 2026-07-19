"""N+1 regression guard for the AI conversation list read path.

``GET /ai/conversations/`` serves ``ConversationListSerializer`` for EVERY
conversation the user owns (the list is unpaginated). ``message_count`` used
to be a ``SerializerMethodField`` running ``obj.messages.count()`` — one
COUNT query per conversation, scaling with the user's whole chat history.

``OrmConversationRepository.list_for_user`` now annotates
``Count("messages")`` and the serializer reads the annotation, so serializing
the repository queryset must stay at ONE query regardless of row count.

The guard exercises the repository + serializer pair directly rather than the
HTTP endpoint: the controller's internal-conversation exclude uses the JSONB
``metadata__contains`` lookup, which the SQLite test backend does not support
(pre-existing; production runs PostgreSQL where it works).
"""
from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from components.agents.infrastructure.repositories.orm_conversation_repository import (
    OrmConversationRepository,
)
from components.agents.mappers.rest.conversations_serializers import (
    ConversationListSerializer,
)
from infrastructure.persistence.ai.conversations.models import (
    Conversation,
    ConversationMessage,
)

pytestmark = [pytest.mark.django_db]


def _make_conversation(user, idx: int, messages: int = 2) -> Conversation:
    conversation = Conversation.objects.create(user=user, title=f"Chat {idx}")
    for n in range(messages):
        ConversationMessage.objects.create(
            conversation=conversation, role="user", content=f"msg {n}"
        )
    return conversation


def _serialize_query_count(user) -> int:
    queryset = OrmConversationRepository().list_for_user(user).order_by("-updated_at")
    with CaptureQueriesContext(connection) as ctx:
        _ = ConversationListSerializer(queryset, many=True).data
    return len(ctx.captured_queries)


def test_conversation_list_query_count_is_constant(user_factory):
    user = user_factory()

    for idx in range(2):
        _make_conversation(user, idx)
    baseline = _serialize_query_count(user)

    # More conversations must NOT grow the query count; the old per-row
    # ``messages.count()`` added one COUNT query per conversation.
    for idx in range(2, 6):
        _make_conversation(user, idx)
    grown = _serialize_query_count(user)

    assert baseline == 1, f"expected a single annotated query, got {baseline}"
    assert grown == baseline, (
        f"Conversation-list N+1 regression: {baseline} queries with 2 "
        f"conversations but {grown} with 6 — the count must be constant "
        "w.r.t. row count."
    )


def test_conversation_list_message_count_is_correct(user_factory):
    """The annotation must keep reporting the real per-conversation count."""
    user = user_factory()
    conversation = _make_conversation(user, 99, messages=3)

    queryset = OrmConversationRepository().list_for_user(user)
    rows = ConversationListSerializer(queryset, many=True).data
    row = next(r for r in rows if r["id"] == str(conversation.id))
    assert row["message_count"] == 3
