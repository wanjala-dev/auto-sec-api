"""ORM implementation of the conversation and message repository ports."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Max
from django.utils import timezone

from components.messaging.application.dto.conversation_list_dto import (
    ConversationListItem,
    LastMessagePreview,
    ParticipantSummary,
)
from components.messaging.domain.entities.conversation_entity import (
    Conversation as ConversationEntity,
    Participant as ParticipantEntity,
)
from components.messaging.domain.entities.message_entity import Message as MessageEntity
from infrastructure.persistence.messaging.models import (
    Conversation,
    ConversationParticipant,
    Message,
)


def _compute_unread_map(user_id: UUID, conversation_ids=None) -> dict:
    """Return ``{conversation_id: unread_count}`` for a viewer in ONE query.

    Unread = non-deleted messages authored by someone else, created after
    the viewer's ``last_read_at`` for that conversation. When
    ``conversation_ids`` is given, scope to exactly those (the list view,
    which has already applied its own archived/starred filters); otherwise
    cover all of the viewer's non-archived conversations (the ``/unread/``
    projection). Replaces the previous per-conversation COUNT loop (N+1).
    """
    part_qs = ConversationParticipant.objects.filter(user_id=user_id)
    if conversation_ids is not None:
        part_qs = part_qs.filter(conversation_id__in=conversation_ids)
    else:
        part_qs = part_qs.filter(is_archived=False)

    last_read = dict(part_qs.values_list("conversation_id", "last_read_at"))
    if not last_read:
        return {}

    ids = list(last_read.keys())
    result: dict[UUID, int] = {cid: 0 for cid in ids}
    rows = (
        Message.objects.filter(conversation_id__in=ids, is_deleted=False)
        .exclude(sender_id=user_id)
        .values_list("conversation_id", "created_at")
    )
    for cid, created in rows:
        lr = last_read.get(cid)
        if lr is None or (created is not None and created > lr):
            result[cid] += 1
    return result


class OrmConversationRepository:
    """Implements ConversationRepositoryPort using Django ORM."""

    # ── Reads ───────────────────────────────────────────────────────

    def find_by_id(self, conversation_id: UUID) -> ConversationEntity | None:
        try:
            conv = (
                Conversation.objects
                .prefetch_related("participants", "participants__user")
                .get(pk=conversation_id)
            )
        except Conversation.DoesNotExist:
            return None
        return self._to_entity(conv)

    def find_private_between(
        self,
        user_id: UUID,
        other_user_id: UUID,
        workspace_id: UUID | None = None,
    ) -> ConversationEntity | None:
        """Find an existing private conversation between two users.

        Uses a subquery approach to find conversations where BOTH users
        are participants, avoiding the old user/receiver asymmetry.
        """
        qs = Conversation.objects.filter(
            conversation_type=Conversation.PRIVATE,
            participants__user_id=user_id,
        ).filter(
            participants__user_id=other_user_id,
        )
        if workspace_id is not None:
            qs = qs.filter(workspace_id=workspace_id)
        else:
            qs = qs.filter(workspace__isnull=True)

        conv = qs.prefetch_related("participants", "participants__user").first()
        if conv is None:
            return None
        return self._to_entity(conv)

    def list_for_user(
        self,
        user_id: UUID,
        *,
        include_archived: bool = False,
        starred_only: bool = False,
    ) -> list[ConversationListItem]:
        """Return the viewer's conversations, enriched for the list view.

        Each item carries the other participant's display fields, a
        last-message preview, and the viewer's unread count — resolved in
        a bounded number of batch queries (no N+1), so the frontend needs
        a single round-trip to render the inbox.
        """
        participant_qs = ConversationParticipant.objects.filter(user_id=user_id)

        if not include_archived:
            participant_qs = participant_qs.filter(is_archived=False)
        if starred_only:
            participant_qs = participant_qs.filter(is_starred=True)

        conversation_ids = list(
            participant_qs.values_list("conversation_id", flat=True)
        )
        if not conversation_ids:
            return []

        # Ordered by latest activity.
        conversations = list(
            Conversation.objects
            .filter(pk__in=conversation_ids)
            .prefetch_related("participants", "participants__user")
            .annotate(last_message_at=Max("messages__created_at"))
            .order_by("-last_message_at", "-updated_at")
        )

        # Latest non-deleted message per conversation — one query, bucketed
        # in Python (portable; DISTINCT ON is Postgres-only and the test DB
        # is SQLite). Rows arrive newest-first per conversation, so the first
        # seen for each conversation is its latest.
        last_by_conv: dict = {}
        for m in (
            Message.objects
            .filter(conversation_id__in=conversation_ids, is_deleted=False)
            .order_by("conversation_id", "-created_at")
        ):
            if m.conversation_id not in last_by_conv:
                last_by_conv[m.conversation_id] = m

        # Viewer's unread counts — one query.
        unread_by_conv = _compute_unread_map(user_id, conversation_ids)

        # The "other" participant of each 1:1, and their display fields — one query.
        other_of: dict = {}
        for conv in conversations:
            other = next(
                (p for p in conv.participants.all() if p.user_id != user_id),
                None,
            )
            if other is not None:
                other_of[conv.id] = other.user_id
        summaries = self._resolve_user_summaries(other_of.values())

        items: list[ConversationListItem] = []
        for conv in conversations:
            other_uid = other_of.get(conv.id)
            preview = None
            msg = last_by_conv.get(conv.id)
            if msg is not None:
                preview = LastMessagePreview(
                    id=msg.id,
                    sender_id=msg.sender_id,
                    body=msg.body,
                    message_type=msg.message_type,
                    created_at=msg.created_at,
                )
            items.append(
                ConversationListItem(
                    conversation=self._to_entity(conv),
                    other_participant=summaries.get(other_uid) if other_uid else None,
                    last_message=preview,
                    unread_count=unread_by_conv.get(conv.id, 0),
                )
            )
        return items

    # ── Writes ──────────────────────────────────────────────────────

    def create(self, entity: ConversationEntity) -> ConversationEntity:
        conv = Conversation.objects.create(
            conversation_type=entity.conversation_type,
            workspace_id=entity.workspace_id,
        )
        for p in entity.participants:
            ConversationParticipant.objects.create(
                conversation=conv,
                user_id=p.user_id,
                role=p.role,
            )
        conv.refresh_from_db()
        conv = (
            Conversation.objects
            .prefetch_related("participants", "participants__user")
            .get(pk=conv.pk)
        )
        return self._to_entity(conv)

    def update_participant_state(
        self,
        conversation_id: UUID,
        user_id: UUID,
        **fields,
    ) -> ParticipantEntity:
        """Update per-participant flags (archive, star, mute, last_read_at)."""
        participant = ConversationParticipant.objects.get(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        now = timezone.now()

        # Auto-set timestamp fields.
        if "is_archived" in fields:
            fields["archived_at"] = now if fields["is_archived"] else None
        if "is_starred" in fields:
            fields["starred_at"] = now if fields["is_starred"] else None

        update_fields = []
        for key, value in fields.items():
            setattr(participant, key, value)
            update_fields.append(key)

        if update_fields:
            participant.save(update_fields=update_fields)

        return self._participant_to_entity(participant)

    # ── Mappers ─────────────────────────────────────────────────────

    @staticmethod
    def _to_entity(conv: Conversation) -> ConversationEntity:
        participants = [
            OrmConversationRepository._participant_to_entity(p)
            for p in conv.participants.all()
        ]
        return ConversationEntity(
            id=conv.id,
            conversation_type=conv.conversation_type,
            workspace_id=conv.workspace_id,
            participants=participants,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
        )

    @staticmethod
    def _resolve_user_summaries(user_ids) -> dict:
        """Batch-resolve ``{user_id: ParticipantSummary}`` in one query.

        Mirrors the ``UserProfile.name`` / ``.photo_url`` display rule used
        elsewhere (e.g. sharing grantee display). Replicated here rather than
        imported to avoid a cross-context infrastructure dependency.
        """
        ids = {u for u in user_ids if u}
        if not ids:
            return {}

        from django.contrib.auth import get_user_model

        User = get_user_model()
        summaries: dict = {}
        for user in User.objects.filter(id__in=ids).select_related("profile"):
            profile = getattr(user, "profile", None)
            display = (
                (getattr(profile, "name", None) or "").strip()
                or " ".join(
                    filter(None, [user.first_name or "", user.last_name or ""])
                ).strip()
                or (user.username or "").strip()
                or ""
            )
            photo_url = ""
            if profile is not None and getattr(profile, "photo_url", ""):
                photo_url = profile.photo_url

            parts = [p for p in display.split() if p]
            if not parts:
                initials = ""
            elif len(parts) == 1:
                initials = parts[0][:2].upper()
            else:
                initials = (parts[0][0] + parts[1][0]).upper()

            summaries[user.id] = ParticipantSummary(
                user_id=user.id,
                display_name=display,
                avatar_url=photo_url,
                initials=initials,
            )
        return summaries

    @staticmethod
    def _participant_to_entity(p: ConversationParticipant) -> ParticipantEntity:
        return ParticipantEntity(
            user_id=p.user_id,
            role=p.role,
            is_archived=p.is_archived,
            is_starred=p.is_starred,
            is_muted=p.is_muted,
            last_read_at=p.last_read_at,
            joined_at=p.joined_at,
        )


class OrmMessageRepository:
    """Implements MessageRepositoryPort using Django ORM."""

    # ── Reads ───────────────────────────────────────────────────────

    def find_by_id(self, message_id: UUID) -> MessageEntity | None:
        try:
            msg = Message.objects.select_related("sender").get(pk=message_id)
        except Message.DoesNotExist:
            return None
        return self._to_entity(msg)

    def list_for_conversation(
        self,
        conversation_id: UUID,
        *,
        limit: int = 50,
        before: UUID | None = None,
    ) -> list[MessageEntity]:
        qs = Message.objects.filter(
            conversation_id=conversation_id,
            is_deleted=False,
        ).select_related("sender")

        if before is not None:
            try:
                cursor_msg = Message.objects.get(pk=before)
                qs = qs.filter(created_at__lt=cursor_msg.created_at)
            except Message.DoesNotExist:
                pass

        messages = qs.order_by("-created_at")[:limit]
        # Return in chronological order.
        return [self._to_entity(m) for m in reversed(messages)]

    # ── Writes ──────────────────────────────────────────────────────

    def create(self, entity: MessageEntity) -> MessageEntity:
        msg = Message.objects.create(
            conversation_id=entity.conversation_id,
            sender_id=entity.sender_id,
            body=entity.body,
            message_type=entity.message_type,
            image=entity.image if entity.image else None,
            metadata=entity.metadata or {},
        )
        # Touch the conversation's updated_at so ordering stays correct.
        Conversation.objects.filter(pk=entity.conversation_id).update(
            updated_at=timezone.now(),
        )
        return self._to_entity(msg)

    def soft_delete(self, message_id: UUID, user_id: UUID) -> bool:
        """Soft-delete a message (only the sender may delete)."""
        updated = Message.objects.filter(
            pk=message_id,
            sender_id=user_id,
            is_deleted=False,
        ).update(is_deleted=True, deleted_at=timezone.now())
        return updated > 0

    def mark_read(self, conversation_id: UUID, user_id: UUID) -> int:
        """Update the participant's last_read_at to now."""
        now = timezone.now()
        updated = ConversationParticipant.objects.filter(
            conversation_id=conversation_id,
            user_id=user_id,
        ).update(last_read_at=now)
        return updated

    def unread_count(self, user_id: UUID) -> dict[UUID, int]:
        """Return {conversation_id: unread_count} for every conversation the user is in."""
        return _compute_unread_map(user_id, None)

    # ── Mappers ─────────────────────────────────────────────────────

    @staticmethod
    def _to_entity(msg: Message) -> MessageEntity:
        return MessageEntity(
            id=msg.id,
            conversation_id=msg.conversation_id,
            sender_id=msg.sender_id,
            body=msg.body,
            message_type=msg.message_type,
            image=msg.image.url if msg.image else None,
            metadata=msg.metadata or {},
            created_at=msg.created_at,
            updated_at=msg.updated_at,
            is_deleted=msg.is_deleted,
            deleted_at=msg.deleted_at,
        )
