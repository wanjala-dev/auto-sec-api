"""Messaging bounded context controller.

All HTTP endpoints for private messaging: conversations, messages,
read receipts, archive/star/mute management.

Every endpoint filters data to the authenticated user — no global
querysets are ever exposed.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from components.messaging.api.requests.conversation_list_request import (
    ConversationListRequest,
)
from components.messaging.api.requests.send_message_request import (
    SendMessageRequest,
)
from components.messaging.api.requests.start_conversation_request import (
    StartConversationRequest,
)
from components.messaging.api.resources.conversation_resources import (
    ConversationManageResource,
    ConversationResource,
    ConversationStartResource,
    LastMessageResource,
    ParticipantResource,
    ParticipantSummaryResource,
)
from components.messaging.api.resources.message_resources import (
    MessageResource,
    UnreadCountResource,
)
from components.messaging.application.providers.conversation_repository_provider import (
    get_conversation_repository_provider,
)
from components.messaging.application.providers.messaging_provider import (
    make_archive_conversation,
    make_delete_message,
    make_get_messages,
    make_list_conversations,
    make_mark_read,
    make_mute_conversation,
    make_send_message,
    make_star_conversation,
    make_start_conversation,
)
from components.messaging.domain.errors import (
    CannotMessageOutsideSharedWorkspaceError,
    CannotMessageSelfError,
    ConversationNotFoundError,
    MessageBodyEmptyError,
    MessageNotFoundError,
    NotAParticipantError,
)
from components.messaging.mappers.rest.messaging_serializers import (
    ConversationSerializer,
    MessageSerializer,
    SendMessageSerializer,
    StartConversationSerializer,
    UnreadCountSerializer,
)

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────


def _conversation_to_resource(
    entity,
    *,
    other_participant=None,
    last_message=None,
    unread_count: int = 0,
) -> dict:
    """Map a Conversation domain entity → ConversationResource → dict.

    ``other_participant`` / ``last_message`` are application-layer read
    models (from a ``ConversationListItem``); when omitted the enrichment
    fields serialize as null/0 (the start-conversation response shape).
    """
    other_resource = None
    if other_participant is not None:
        other_resource = ParticipantSummaryResource(
            user_id=other_participant.user_id,
            display_name=other_participant.display_name,
            avatar_url=other_participant.avatar_url,
            initials=other_participant.initials,
        )
    last_resource = None
    if last_message is not None:
        last_resource = LastMessageResource(
            id=last_message.id,
            sender_id=last_message.sender_id,
            body=last_message.body,
            message_type=last_message.message_type,
            created_at=last_message.created_at,
        )
    resource = ConversationResource(
        id=entity.id,
        conversation_type=entity.conversation_type,
        workspace_id=entity.workspace_id,
        participants=[
            ParticipantResource(
                user_id=p.user_id,
                role=p.role,
                is_archived=p.is_archived,
                is_starred=p.is_starred,
                is_muted=p.is_muted,
                last_read_at=p.last_read_at,
                joined_at=p.joined_at,
            )
            for p in entity.participants
        ],
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        other_participant=other_resource,
        last_message=last_resource,
        unread_count=unread_count,
    )
    from dataclasses import asdict
    return asdict(resource)


def _conversation_item_to_resource(item) -> dict:
    """Map an application ConversationListItem → enriched resource dict."""
    return _conversation_to_resource(
        item.conversation,
        other_participant=item.other_participant,
        last_message=item.last_message,
        unread_count=item.unread_count,
    )


def _message_to_resource(entity) -> dict:
    """Map a Message domain entity → MessageResource → dict."""
    resource = MessageResource(
        id=entity.id,
        conversation_id=entity.conversation_id,
        sender_id=entity.sender_id,
        body=entity.body,
        message_type=entity.message_type,
        image=entity.image,
        metadata=getattr(entity, "metadata", {}) or {},
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        is_deleted=entity.is_deleted,
    )
    from dataclasses import asdict
    return asdict(resource)


# ── Throttles ───────────────────────────────────────────────────────


class MessageSendThrottle(UserRateThrottle):
    """Limit message sending to prevent spam."""

    rate = "60/min"


# ── Conversations ───────────────────────────────────────────────────


class ConversationListController(APIView):
    """GET /messaging/conversations/

    List all conversations for the authenticated user.

    Query params:
        include_archived (bool) — include archived conversations (default: false)
        starred_only (bool) — only return starred conversations (default: false)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        req = ConversationListRequest(
            include_archived=request.query_params.get("include_archived", "").lower() == "true",
            starred_only=request.query_params.get("starred_only", "").lower() == "true",
        )
        use_case = make_list_conversations()
        conversations = use_case.execute(
            user_id=request.user.id,
            include_archived=req.include_archived,
            starred_only=req.starred_only,
        )
        data = [_conversation_item_to_resource(c) for c in conversations]
        serializer = ConversationSerializer(data, many=True)
        return Response(serializer.data)


class ConversationStartController(APIView):
    """POST /messaging/conversations/

    Start a new private conversation (or return existing).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        input_serializer = StartConversationSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        req = StartConversationRequest(**input_serializer.validated_data)

        use_case = make_start_conversation()
        try:
            result = use_case.execute(
                initiator_id=request.user.id,
                recipient_id=req.recipient_id,
                workspace_id=req.workspace_id,
            )
        except CannotMessageSelfError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except CannotMessageOutsideSharedWorkspaceError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        output = ConversationSerializer(_conversation_to_resource(result.conversation))
        http_status = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return Response(output.data, status=http_status)


# ── Conversation management (archive, star, mute) ──────────────────


class ConversationArchiveController(APIView):
    """POST /messaging/conversations/<id>/archive/
    POST /messaging/conversations/<id>/unarchive/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id, action):
        archive = action == "archive"
        use_case = make_archive_conversation()
        try:
            participant = use_case.execute(
                conversation_id=conversation_id,
                user_id=request.user.id,
                archive=archive,
            )
        except (ConversationNotFoundError, NotAParticipantError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        resource = ConversationManageResource(
            conversation_id=conversation_id,
            is_archived=participant.is_archived,
        )
        from dataclasses import asdict
        return Response(asdict(resource))


class ConversationStarController(APIView):
    """POST /messaging/conversations/<id>/star/
    POST /messaging/conversations/<id>/unstar/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id, action):
        star = action == "star"
        use_case = make_star_conversation()
        try:
            participant = use_case.execute(
                conversation_id=conversation_id,
                user_id=request.user.id,
                star=star,
            )
        except (ConversationNotFoundError, NotAParticipantError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        resource = ConversationManageResource(
            conversation_id=conversation_id,
            is_starred=participant.is_starred,
        )
        from dataclasses import asdict
        return Response(asdict(resource))


class ConversationMuteController(APIView):
    """POST /messaging/conversations/<id>/mute/
    POST /messaging/conversations/<id>/unmute/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id, action):
        mute = action == "mute"
        use_case = make_mute_conversation()
        try:
            participant = use_case.execute(
                conversation_id=conversation_id,
                user_id=request.user.id,
                mute=mute,
            )
        except (ConversationNotFoundError, NotAParticipantError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        resource = ConversationManageResource(
            conversation_id=conversation_id,
            is_muted=participant.is_muted,
        )
        from dataclasses import asdict
        return Response(asdict(resource))


# ── Messages ────────────────────────────────────────────────────────


class MessageListController(APIView):
    """GET  /messaging/conversations/<id>/messages/

    Fetch messages for a conversation (cursor-based pagination).

    Query params:
        limit (int)  — max messages to return (default: 50, max: 100)
        before (uuid) — return messages before this message ID
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        use_case = make_get_messages()
        limit = min(int(request.query_params.get("limit", 50)), 100)
        before = request.query_params.get("before")

        try:
            messages = use_case.execute(
                conversation_id=conversation_id,
                user_id=request.user.id,
                limit=limit,
                before=before,
            )
        except (ConversationNotFoundError, NotAParticipantError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        data = [_message_to_resource(m) for m in messages]
        serializer = MessageSerializer(data, many=True)
        return Response(serializer.data)


class MessageSendController(APIView):
    """POST /messaging/conversations/<id>/messages/

    Send a message in an existing conversation. Accepts JSON (text only)
    or multipart/form-data (text and/or an ``image`` file attachment).
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_classes = [MessageSendThrottle]

    def post(self, request, conversation_id):
        input_serializer = SendMessageSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        validated = dict(input_serializer.validated_data)
        image = validated.pop("image", None)
        req = SendMessageRequest(
            body=validated.get("body", ""),
            message_type=validated.get("message_type", "text"),
        )

        use_case = make_send_message()
        try:
            message = use_case.execute(
                conversation_id=conversation_id,
                sender_id=request.user.id,
                body=req.body,
                message_type=req.message_type,
                image=image,
                metadata=validated.get("metadata") or {},
            )
        except (ConversationNotFoundError, NotAParticipantError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except MessageBodyEmptyError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        output = MessageSerializer(_message_to_resource(message))
        return Response(output.data, status=status.HTTP_201_CREATED)


class MessageDeleteController(APIView):
    """DELETE /messaging/messages/<id>/

    Soft-delete a message (sender only).
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, message_id):
        use_case = make_delete_message()
        try:
            use_case.execute(message_id=message_id, user_id=request.user.id)
        except (MessageNotFoundError, ConversationNotFoundError, NotAParticipantError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Read receipts ───────────────────────────────────────────────────


class MarkReadController(APIView):
    """POST /messaging/conversations/<id>/read/

    Mark all messages in a conversation as read for the current user.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        use_case = make_mark_read()
        try:
            use_case.execute(
                conversation_id=conversation_id,
                user_id=request.user.id,
            )
        except (ConversationNotFoundError, NotAParticipantError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response({"marked_read": True})


class UnreadCountController(APIView):
    """GET /messaging/unread/

    Return unread message counts per conversation.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        counts = get_conversation_repository_provider().unread_count(
            request.user.id
        )
        data = [
            UnreadCountResource(conversation_id=cid, count=c)
            for cid, c in counts.items()
            if c > 0
        ]
        from dataclasses import asdict
        serializer = UnreadCountSerializer([asdict(r) for r in data], many=True)
        total = sum(c for c in counts.values() if c > 0)
        return Response({"total": total, "conversations": serializer.data})
