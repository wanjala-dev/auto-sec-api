import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.db.models import Q

from components.knowledge.infrastructure.factories.openai_breaker import (
    OPENAI_EMBEDDINGS_SLUG,
    OpenAIUnavailableError,
    openai_allow_request,
    record_openai_failure,
    record_openai_success,
)
from components.knowledge.infrastructure.factories.vector_stores.factory import VectorStoreFactory
from infrastructure.persistence.workspaces.models import Action, Workspace, WorkspaceComment

logger = logging.getLogger(__name__)


def _guarded_add_texts(vector_store, *, texts, metadatas):
    """Embed + store ``texts`` behind the OpenAI embeddings circuit breaker.

    ``vector_store.add_texts`` is where the OpenAI embeddings network call
    actually happens. Gating here means a down provider fails fast across the
    whole process instead of every per-item loop exhausting its retry budget
    against a dead endpoint (celery-tasks skill §3e). Success/failure is
    recorded so the breaker can open and later probe recovery.
    """
    if not openai_allow_request(OPENAI_EMBEDDINGS_SLUG):
        raise OpenAIUnavailableError(OPENAI_EMBEDDINGS_SLUG)
    try:
        result = vector_store.add_texts(texts=texts, metadatas=metadatas)
    except Exception:
        record_openai_failure(OPENAI_EMBEDDINGS_SLUG)
        raise
    record_openai_success(OPENAI_EMBEDDINGS_SLUG)
    return result


@shared_task(
    name="infrastructure.ai.embeddings.tasks.create_embeddings_for_workspace_content",
    bind=True,
    max_retries=2,
    retry_backoff=True,
    soft_time_limit=480,
    time_limit=600,
)
def create_embeddings_for_workspace_content(self):
    """
    Daily task to create embeddings for workspace content
    Runs once per day to process new or updated content

    Failures propagate so Celery's autoretry / task_failure signal can act —
    swallowing them here hid bugs and made the retry config dead (celery-tasks
    skill §3). The per-model helpers below keep their own log-and-continue
    loops, so a single bad row doesn't abort the whole run; only a task-level
    failure (e.g. OpenAI breaker open) surfaces here.
    """
    logger.info("Starting daily embeddings creation task")

    # Get content that needs embeddings (created or updated in the last 24 hours)
    yesterday = datetime.now() - timedelta(days=1)

    # Process Workspaces
    workspaces_processed = process_workspaces(yesterday)

    # Process Actions
    actions_processed = process_actions(yesterday)

    # Process Comments
    comments_processed = process_comments(yesterday)

    # Process Conversation history (chat → RAG). This sub-task has its own
    # log-and-continue loop; a clean count of 0 on failure is acceptable here.
    conversations_processed = 0
    try:
        conversations_processed = create_embeddings_for_conversations()
    except Exception:
        logger.exception("Conversation embedding sub-task failed")

    total_processed = workspaces_processed + actions_processed + comments_processed + conversations_processed

    logger.info(f"Embeddings task completed. Total processed: {total_processed}")

    return {
        "status": "success",
        "workspaces_processed": workspaces_processed,
        "actions_processed": actions_processed,
        "comments_processed": comments_processed,
        "conversations_processed": conversations_processed,
        "total_processed": total_processed,
    }


@shared_task(
    name="infrastructure.ai.embeddings.tasks.create_embeddings_for_workspace",
    bind=True,
    max_retries=2,
    retry_backoff=True,
    soft_time_limit=480,
    time_limit=600,
)
def create_embeddings_for_workspace(self, workspace_id: str, force: bool = False):
    """Create embeddings immediately for a specific workspace and its related content.

    Used for post-save hooks so a new workspace is immediately searchable/usable in chat.
    Skipped when ai_teammate_enabled is False (unless force=True), so workspaces that
    don't use AI don't waste embedding spend.
    """
    try:
        workspace = Workspace.objects.filter(id=workspace_id).first()
        if not workspace:
            return {"status": "error", "message": f"Workspace {workspace_id} not found"}

        # Gate: only embed when AI is enabled for this workspace
        if not force and not getattr(workspace, "ai_teammate_enabled", False):
            logger.info(f"Skipping embeddings for workspace {workspace_id}: ai_teammate_enabled=False")
            return {"status": "skipped", "reason": "ai_teammate_disabled"}

        vector_store = VectorStoreFactory.create_vector_store()

        processed = {
            "workspace": 0,
            "actions": 0,
            "comments": 0,
        }

        # Workspace story/shared body
        try:
            content_parts = []
            if workspace.workspace_story:
                content_parts.append(workspace.workspace_story)
            if workspace.shared_body:
                content_parts.append(workspace.shared_body)
            if content_parts:
                combined_content = " ".join(content_parts)
                _guarded_add_texts(
                    vector_store,
                    texts=[combined_content],
                    metadatas=[
                        {
                            "type": "workspace",
                            "workspace_id": str(workspace.id),
                            "workspace_name": workspace.workspace_name,
                            "owner_id": str(workspace.workspace_owner.id),
                            "created_at": workspace.created_at.isoformat(),
                            "updated_at": workspace.updated_at.isoformat(),
                            "privacy": workspace.privacy,
                            "status": workspace.status,
                        }
                    ],
                )
                processed["workspace"] = 1
        except Exception:
            logger.exception(f"Failed to embed workspace {workspace.id}")

        # Recent related content (limit to avoid heavy load)
        try:
            actions = Action.objects.filter(workspace_id=workspace_id).order_by("-created_date")[:100]
            for a in actions:
                content = f"{a.title} {a.body}".strip()
                if content:
                    _guarded_add_texts(
                        vector_store,
                        texts=[content],
                        metadatas=[
                            {
                                "type": "action",
                                "action_id": str(a.id),
                                "title": a.title,
                                "workspace_id": str(workspace_id),
                                "owner_id": str(a.owner.id),
                                "created_at": a.created_date.isoformat(),
                                "updated_at": a.updated_at.isoformat(),
                                "privacy": a.privacy,
                            }
                        ],
                    )
                    processed["actions"] += 1
        except Exception:
            logger.exception(f"Failed to embed actions for workspace {workspace_id}")

        try:
            # ``seeds`` was renamed to ``workspace`` long ago — the stale kwarg made
            # this section crash (caught + logged) on EVERY run, so workspace
            # comments never embedded. Surfaced by the provisioning test 2026-07-13.
            comments = WorkspaceComment.objects.filter(workspace_id=workspace_id).order_by("-created_on")[:200]
            for c in comments:
                if c.comment:
                    _guarded_add_texts(
                        vector_store,
                        texts=[c.comment],
                        metadatas=[
                            {
                                "type": "comment",
                                "comment_id": str(c.id),
                                "workspace_id": str(workspace_id),
                                "author_id": str(c.author.id),
                                "created_at": c.created_on.isoformat(),
                                "privacy": c.privacy,
                                "is_parent": c.is_parent,
                            }
                        ],
                    )
                    processed["comments"] += 1
        except Exception:
            logger.exception(f"Failed to embed comments for workspace {workspace_id}")

        return {"status": "success", **processed}
    except Exception:
        # Do NOT swallow — let transient errors (OpenAI breaker open, timeouts,
        # DB blips) reach Celery's autoretry / task_failure signal. Swallowing
        # here made the retry config dead and hid bugs (celery-tasks skill §3).
        logger.exception("Embeddings task for workspace %s failed", workspace_id)
        raise


def process_workspaces(since_date):
    """Process Workspace model content for embeddings.

    Only processes workspaces with ai_teammate_enabled=True. Workspaces that
    don't use AI are skipped to avoid wasting embedding spend.
    """
    try:
        # Get workspaces that were created or updated since the given date
        # AND have AI enabled (no point embedding for orgs not using AI)
        workspaces = (
            Workspace.objects.filter(
                ai_teammate_enabled=True,
            )
            .filter(Q(created_at__gte=since_date) | Q(updated_at__gte=since_date))
            .exclude(
                # Exclude only when BOTH workspace_story and shared_body are empty
                (Q(workspace_story__isnull=True) | Q(workspace_story=""))
                & (Q(shared_body__isnull=True) | Q(shared_body=""))
            )
        )

        if not workspaces.exists():
            logger.info("No workspaces need embeddings")
            return 0

        # Initialize vector store (uses OpenAI embeddings by default)
        vector_store = VectorStoreFactory.create_vector_store()

        processed_count = 0
        for workspace in workspaces:
            try:
                # Combine workspace story and shared body for embedding
                content_parts = []
                if workspace.workspace_story:
                    content_parts.append(workspace.workspace_story)
                if workspace.shared_body:
                    content_parts.append(workspace.shared_body)

                if content_parts:
                    combined_content = " ".join(content_parts)

                    # Store in vector store
                    _guarded_add_texts(
                        vector_store,
                        texts=[combined_content],
                        metadatas=[
                            {
                                "type": "workspace",
                                "workspace_id": str(workspace.id),
                                "workspace_name": workspace.workspace_name,
                                "owner_id": str(workspace.workspace_owner.id),
                                "created_at": workspace.created_at.isoformat(),
                                "updated_at": workspace.updated_at.isoformat(),
                                "privacy": workspace.privacy,
                                "status": workspace.status,
                            }
                        ],
                    )

                    processed_count += 1
                    logger.info(f"Processed workspace: {workspace.workspace_name}")

            except Exception:
                logger.exception(f"Failed to process workspace {workspace.id}")
                continue

        logger.info(f"Processed {processed_count} workspaces")
        return processed_count

    except Exception:
        logger.exception("Failed to process workspaces")
        return 0


def process_actions(since_date):
    """Process Action model content for embeddings (only AI-enabled workspaces)"""
    try:
        actions = (
            Action.objects.filter(
                workspace__ai_teammate_enabled=True,
            )
            .filter(Q(created_date__gte=since_date) | Q(updated_at__gte=since_date))
            .exclude(
                # Exclude only when BOTH title and body are empty
                (Q(title__isnull=True) | Q(title="")) & (Q(body__isnull=True) | Q(body=""))
            )
        )

        if not actions.exists():
            logger.info("No actions need embeddings")
            return 0

        vector_store = VectorStoreFactory.create_vector_store()

        processed_count = 0
        for action in actions:
            try:
                # Combine title and body for embedding
                content = f"{action.title} {action.body}".strip()

                if content:
                    _guarded_add_texts(
                        vector_store,
                        texts=[content],
                        metadatas=[
                            {
                                "type": "action",
                                "action_id": str(action.id),
                                "title": action.title,
                                "workspace_id": str(action.workspace.id),
                                "owner_id": str(action.owner.id),
                                "created_at": action.created_date.isoformat(),
                                "updated_at": action.updated_at.isoformat(),
                                "privacy": action.privacy,
                            }
                        ],
                    )

                    processed_count += 1
                    logger.info(f"Processed action: {action.title}")

            except Exception:
                logger.exception(f"Failed to process action {action.id}")
                continue

        logger.info(f"Processed {processed_count} actions")
        return processed_count

    except Exception:
        logger.exception("Failed to process actions")
        return 0


def process_comments(since_date):
    """Process WorkspaceComment model content for embeddings (only AI-enabled workspaces)"""
    try:
        comments = WorkspaceComment.objects.filter(
            workspace__ai_teammate_enabled=True,
            created_on__gte=since_date,
        ).exclude(Q(comment__isnull=True) | Q(comment=""))

        if not comments.exists():
            logger.info("No comments need embeddings")
            return 0

        vector_store = VectorStoreFactory.create_vector_store()

        processed_count = 0
        for comment in comments:
            try:
                if comment.comment:
                    _guarded_add_texts(
                        vector_store,
                        texts=[comment.comment],
                        metadatas=[
                            {
                                "type": "comment",
                                "comment_id": str(comment.id),
                                "workspace_id": str(comment.workspaces.id),
                                "author_id": str(comment.author.id),
                                "created_at": comment.created_on.isoformat(),
                                "privacy": comment.privacy,
                                "is_parent": comment.is_parent,
                            }
                        ],
                    )

                    processed_count += 1
                    logger.info(f"Processed comment: {comment.id}")

            except Exception:
                logger.exception(f"Failed to process comment {comment.id}")
                continue

        logger.info(f"Processed {processed_count} comments")
        return processed_count

    except Exception:
        logger.exception("Failed to process comments")
        return 0


@shared_task(
    name="infrastructure.ai.embeddings.tasks.create_embeddings_for_all_content",
    bind=True,
    max_retries=2,
    retry_backoff=True,
    soft_time_limit=480,
    time_limit=600,
)
def create_embeddings_for_all_content(self):
    """
    One-time task to create embeddings for all existing content
    Use this for initial setup or to reprocess all content

    Failures propagate so the retry config / task_failure signal can act; the
    per-model helpers keep their own log-and-continue loops (celery-tasks §3).
    """
    logger.info("Starting full embeddings creation task")

    # Process all content regardless of date
    workspaces_processed = process_workspaces(datetime.min)
    actions_processed = process_actions(datetime.min)
    comments_processed = process_comments(datetime.min)

    total_processed = workspaces_processed + actions_processed + comments_processed

    logger.info(f"Full embeddings task completed. Total processed: {total_processed}")

    return {
        "status": "success",
        "workspaces_processed": workspaces_processed,
        "actions_processed": actions_processed,
        "comments_processed": comments_processed,
        "total_processed": total_processed,
    }


# ── Conversation history embedding (RAG over past chats) ────────────


@shared_task(
    name="infrastructure.ai.embeddings.tasks.create_embeddings_for_conversations",
    bind=True,
    max_retries=2,
    retry_backoff=True,
    soft_time_limit=480,
    time_limit=600,
)
def create_embeddings_for_conversations(self):
    """Embed recent conversation messages so past chats become searchable via RAG.

    Groups messages by conversation, concatenates exchanges, and indexes
    each conversation turn as a separate chunk with workspace/user metadata.
    Runs daily alongside the other embedding tasks.
    """
    from infrastructure.persistence.ai.conversations.models import (
        Conversation,
        ConversationMessage,
    )

    yesterday = datetime.now() - timedelta(days=1)
    processed_count = 0

    try:
        vector_store = VectorStoreFactory.create_vector_store()

        # Find conversations with recent messages
        recent_conversations = (
            Conversation.objects.filter(
                messages__created_at__gte=yesterday,
                is_active=True,
            )
            .distinct()
            .prefetch_related("messages")
        )

        for conversation in recent_conversations:
            try:
                workspace_id = (conversation.metadata or {}).get("workspace_id", "")
                agent_type = (conversation.metadata or {}).get("agent_type", "")

                # Get recent messages (last 24h) for this conversation
                recent_messages = ConversationMessage.objects.filter(
                    conversation=conversation,
                    created_at__gte=yesterday,
                ).order_by("created_at")

                if not recent_messages.exists():
                    continue

                # Build exchange pairs (human + assistant)
                exchanges = []
                current_exchange = []
                for msg in recent_messages:
                    current_exchange.append(f"{msg.role}: {msg.content}")
                    if msg.role == "assistant":
                        exchanges.append("\n".join(current_exchange))
                        current_exchange = []
                if current_exchange:
                    exchanges.append("\n".join(current_exchange))

                # Index each exchange as a separate chunk
                for i, exchange in enumerate(exchanges):
                    if not exchange.strip():
                        continue

                    _guarded_add_texts(
                        vector_store,
                        texts=[exchange],
                        metadatas=[
                            {
                                "type": "conversation",
                                "conversation_id": str(conversation.id),
                                "workspace_id": workspace_id,
                                "user_id": str(conversation.user_id) if conversation.user_id else "",
                                "agent_type": agent_type,
                                "exchange_index": i,
                                "created_at": conversation.updated_at.isoformat() if conversation.updated_at else "",
                            }
                        ],
                    )
                    processed_count += 1

            except Exception:
                logger.exception("Failed to embed conversation %s", conversation.id)
                continue

        logger.info(f"Embedded {processed_count} conversation exchanges")
        return processed_count

    except Exception:
        # Do NOT swallow — let transient errors reach Celery's autoretry /
        # task_failure signal instead of masking them as a 0 count
        # (celery-tasks skill §3). The per-conversation loop above keeps its
        # own log-and-continue so a single bad row doesn't abort the run.
        logger.exception("Conversation embedding task failed")
        raise
