"""
Unified AI API Controller - Merged from 11 modules per architecture standard
Refactored with ViewSets and Router
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from dataclasses import asdict
from uuid import UUID

import requests
from django.contrib.auth import get_user_model
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import status, throttling, viewsets
from rest_framework.decorators import action, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from components.agents.api.permissions import AiKillSwitchPermission, PostureDashboardPermission
from components.agents.api.resources.agent_chat_resource import (
    AgentChatErrorResource,
    AgentChatResource,
)
from components.agents.application.commands.agent_chat_command import (
    AgentChatCommand,
    AgentChatFailure,
    AgentChatSuccess,
)
from components.agents.application.commands.agent_lifecycle_command import (
    AgentStateCommand,
    AgentStateFailure,
    CreateAgentCommand,
    CreateAgentFailure,
    DeleteAgentCommand,
    DeleteAgentFailure,
)
from components.agents.application.commands.deep_run_command import (
    DeepPlanAndRunCommand,
    DeepRunFailure,
    DeepRunPlanCommand,
)
from components.agents.application.commands.pdf_chat_command import (
    PdfChatCommand,
    PdfChatNoContent,
    PdfChatNoRelevantDocs,
    PdfChatSuccess,
)
from components.agents.application.commands.pdf_summary_command import (
    PdfSummaryCommand,
    PdfSummaryFailure,
    PdfSummaryNoContent,
)
from components.agents.application.ports.agent_engagement_port import (
    CommentRequest,
    FollowRequest,
    LikeRequest,
    RateRequest,
    RevokeShareRequest,
    ShareRequest,
)
from components.agents.application.ports.agent_engagement_query_port import (
    GetSharedAgentRequest,
    ListCommentsRequest,
    ListRatingsRequest,
)
from components.agents.application.queries.workspace_search_query import WorkspaceSearchRequest
from components.agents.application.service import AgentsService
from components.agents.application.use_cases.deep_run_use_case import default_plan_payload
from components.agents.domain.errors import (
    AgentDisabledError,
    AgentEngagementError,
    AgentNotFoundError,
    AgentPermissionError,
    AiRunLimitExceeded,
    AiUnavailable,
    InvalidCommentError,
    InvalidShareScopeError,
    ShareNotFoundError,
)
from components.agents.mappers.rest.conversations_serializers import (
    ConversationListSerializer,
    ConversationMessageSerializer,
    ConversationSerializer,
    CreateConversationSerializer,
    CreateMessageSerializer,
)
from components.shared_platform.api.permissions import RequiresFeatureFlag
from components.shared_platform.application.providers.core_validators_provider import (
    get_core_validators_provider,
)

ensure_uuid = get_core_validators_provider().ensure_uuid

User = get_user_model()
logger = logging.getLogger(__name__)
_RETRYABLE_EXCEPTIONS = (TimeoutError, ConnectionError)

# ── Service instance ──────────────────────────────────────────────────
agents_service = AgentsService()


# ── Throttle Classes ──
class CommentsThrottle(throttling.UserRateThrottle):
    rate = "30/min"


class RatingsThrottle(throttling.UserRateThrottle):
    rate = "20/min"


class LikesThrottle(throttling.UserRateThrottle):
    rate = "120/min"


class SharesThrottle(throttling.UserRateThrottle):
    rate = "10/hour"


class SettingsThrottle(throttling.UserRateThrottle):
    rate = "30/hour"


# ── Helper Functions ──
def _schema(request_body: bool = False):
    if request_body:
        return extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    return extend_schema(request=None, responses=OpenApiTypes.OBJECT)


def _has_teammate_permissions(user, workspace, *, include_followers: bool = False) -> bool:
    """Return True when the user may view or edit the workspace's Orchestrator."""
    if not user or not workspace:
        return False
    if getattr(user, "is_staff", False):
        return True
    if str(workspace.workspace_owner_id) == str(getattr(user, "id", None)):
        return True
    if workspace.workspace_teams.filter(
        members=user,
        status="active",
    ).exists():
        return True
    if include_followers:
        return workspace.followers.filter(id=getattr(user, "id", None)).exists()
    return False


def _has_agent_access(user, agent_record, *, include_followers: bool = False) -> bool:
    """Return True when the user may view the agent's data."""
    if not user or not agent_record:
        return False
    if str(agent_record.user_id) == str(getattr(user, "id", None)):
        return True
    workspace = agent_record.workspace
    if not workspace:
        return False
    return _has_teammate_permissions(user, workspace, include_followers=include_followers)


def _parse_bool(value):
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int(value, default=None, *, min_value: int | None = None):
    """Parse an integer query parameter with optional bounds."""
    if value is None:
        return default
    value_str = str(value).strip()
    if not value_str:
        return default
    if value_str.lower() in {"all", "none"}:
        return None
    try:
        parsed = int(value_str)
    except (TypeError, ValueError):
        return default
    if min_value is not None and parsed < min_value:
        return min_value
    return parsed


def _engagement_error_response(exc: Exception) -> Response:
    """Map domain errors from engagement operations to HTTP responses."""
    if isinstance(exc, AgentNotFoundError):
        return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, ShareNotFoundError):
        return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, AgentDisabledError):
        return Response({"error": str(exc), "code": "agent_disabled"}, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, AgentPermissionError):
        code = status.HTTP_401_UNAUTHORIZED if "Authentication" in str(exc) else status.HTTP_403_FORBIDDEN
        return Response({"error": str(exc)}, status=code)
    if isinstance(exc, (AgentEngagementError, InvalidCommentError, InvalidShareScopeError)):
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"error": "Internal error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _ai_run_limit_response(exc: AiRunLimitExceeded) -> Response:
    """Map a spent metered-AI allowance to HTTP 402 with an upgrade nudge."""
    return Response(
        {
            "error": str(exc),
            "code": "ai_run_limit_exceeded",
            "used": exc.used,
            "limit": exc.limit,
            "upgrade_required": True,
        },
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


def _ai_unavailable_response(exc: AiUnavailable) -> Response:
    """Map an engaged AI kill switch to HTTP 503 (transient, operator-controlled)."""
    return Response(
        {"error": str(exc), "code": "ai_unavailable"},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _sse_event(event: str, payload: dict) -> str:
    """Format a Server-Sent Events (SSE) message with JSON payload."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _resolve_llm_provider(request):
    """Resolve optional LLM provider override without colliding with retriever provider."""
    return request.data.get("llm_provider") or request.data.get("llm") or None


def _invoke_llm_with_retry(llm, messages, *, max_attempts: int = 3, base_delay_seconds: float = 0.5):
    """Invoke an LLM call with bounded retries for transient transport failures."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return llm(messages)
        except _RETRYABLE_EXCEPTIONS as exc:
            retryable = attempt < max_attempts
            logger.warning(
                "ai.chain.llm.retry",
                extra={
                    "retry": {
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "retryable": retryable,
                        "error_type": type(exc).__name__,
                    }
                },
            )
            if not retryable:
                raise
            backoff = base_delay_seconds * (2 ** (attempt - 1))
            jitter = backoff * random.uniform(-0.2, 0.2)
            time.sleep(max(0.0, backoff + jitter))


def _is_elasticsearch_configured() -> bool:
    """Lightweight check for Elasticsearch configuration via env vars."""
    es_url = os.environ.get("ELASTICSEARCH_URL")
    es_index = os.environ.get("ELASTICSEARCH_INDEX_NAME")
    return bool(es_url) and bool(es_index)


def _stream_retrieval_events(*, request, question: str, conversation_id: str, provider: str, k: int):
    from components.agents.application.providers.retrieval_chain_provider import (
        get_retrieval_chain_provider,
    )

    _retrieval_provider = get_retrieval_chain_provider()

    yield _sse_event(
        "meta",
        {
            "conversation_id": conversation_id,
            "provider": provider,
            "k": k,
        },
    )

    use_mock = request.data.get("mock", False)
    if use_mock:
        yield _sse_event(
            "token",
            {"token": f"Mock retrieval response for '{question}'"},
        )
        yield _sse_event("done", {"status": "ok", "mock": True})
        return

    class ChatArgs:
        def __init__(self, conversation_id, pdf_id=None):
            self.conversation_id = conversation_id
            self.pdf_id = pdf_id

    chat_args = ChatArgs(conversation_id)

    try:
        llm = agents_service.get_llm_port(
            provider=_resolve_llm_provider(request),
            model_name=request.data.get("model_name", "gpt-3.5-turbo"),
            temperature=0.3,
            streaming=True,
        )
        retriever = agents_service.get_vector_store_port(
            provider=provider,
        ).search(
            query=question,
            k=k,
        )
        retrieval_chain = _retrieval_provider.streaming_chain_from_llm(
            llm=llm,
            retriever=retriever,
            return_source_documents=False,
            metadata={"conversation_id": conversation_id},
        )
        for token in retrieval_chain.stream_retrieval(question):
            if token.startswith("Error:"):
                yield _sse_event("error", {"message": token})
                yield _sse_event("done", {"status": "error"})
                return
            yield _sse_event("token", {"token": token})
        yield _sse_event("done", {"status": "ok"})
    except Exception as exc:
        yield _sse_event("error", {"message": str(exc)})
        yield _sse_event("done", {"status": "error"})


def _run_embedding_for_file(file_obj, pdf_id: str, workspace_id: str, user_id: str):
    """Dispatch to the correct embedding creator based on file type."""
    from components.knowledge.application.providers.embeddings_provider import (
        get_embeddings_provider,
    )

    _embeddings_provider = get_embeddings_provider()

    if file_obj.file_type == "pdf":
        return _embeddings_provider.create_for_pdf(
            pdf_id=str(pdf_id),
            pdf_path=file_obj.file.path,
            user_id=str(user_id),
            workspace_id=str(workspace_id),
        )

    if file_obj.file_type == "document":
        return _embeddings_provider.create_for_document(
            file_id=str(pdf_id),
            file_path=file_obj.file.path,
            user_id=str(user_id),
            workspace_id=str(workspace_id),
        )

    return {"success": False, "error": "Unsupported file type for embeddings"}


def _log_response(conversation: Conversation | None, payload: dict, *, context: str = "workspace_chat") -> None:
    """Log workspace chat responses for debugging/audit."""
    pass  # Placeholder


# ── AI Findings ViewSet ──
#
# Phase 5 of the Agents-as-Teammates migration
# (``docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md``). The canonical
# read surface for every AI finding — replaces the deleted
# ``/ai/actions/`` endpoint. Returns Kanban tasks created by
# specialist handlers + the detector cycle, scoped to the workspace's
# AI agent team board. Tasks carry ``source_type='ai.<action_type>'``
# and their agent attribution + detector context lives on
# ``Task.metadata`` (see ``persist_finding_as_task``).
#
# Supported filters:
#   workspace_id, source_type (exact), source_type_prefix (LIKE 'X%'),
#   recipient_id, campaign_id, event_id, grant_id, project_id,
#   task_id, column_title.
class AIFindingsViewSet(viewsets.GenericViewSet):
    """List AI findings as Kanban tasks scoped to the workspace's agent team."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        from components.project.application.providers.project_models_provider import (
            get_project_models_provider,
        )

        _pkg_models = get_project_models_provider()
        Task = _pkg_models.Task
        from components.team.application.providers.team_models_provider import (
            get_team_models_provider,
        )

        _pkg_models = get_team_models_provider()
        Team = _pkg_models.Team

        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response(
                {"error": "workspace_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            normalized_workspace_id = str(ensure_uuid(workspace_id, field_name="workspace_id"))
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Scope to the workspace's agent team (the same one
        # ``ensure_agents_board`` provisions). Tasks not on the agent
        # team are NOT AI findings — the read endpoint must not leak
        # human-created tasks even if they happen to have a non-empty
        # source_type.
        agent_team = (
            Team.objects.filter(
                workspace_id=normalized_workspace_id,
                kind=Team.Kind.AI_AGENTS,
                status=Team.ACTIVE,
            )
            .only("id")
            .first()
        )
        if agent_team is None:
            # No agent team yet (transitional workspace) — return empty
            # paginated response. Frontend widgets render the no-findings
            # state correctly off this.
            return Response({"count": 0, "next": None, "previous": None, "results": []})

        queryset = (
            Task.objects.filter(
                workspace_id=normalized_workspace_id,
                team_id=agent_team.id,
            )
            .exclude(source_type="")
            .select_related(
                "workspace",
                "team",
                "project",
                "column",
                "recipient",
                "campaign",
                "event",
                "grant",
            )
            .order_by("-created_at")
        )

        # ── source_type filters ──────────────────────────────────────
        source_type = request.query_params.get("source_type")
        source_type_prefix = request.query_params.get("source_type_prefix")
        if source_type:
            queryset = queryset.filter(source_type=source_type)
        if source_type_prefix:
            queryset = queryset.filter(source_type__startswith=source_type_prefix)

        # ── Entity FK filters ────────────────────────────────────────
        for query_key, model_field in _FINDINGS_FK_FILTERS.items():
            raw_value = request.query_params.get(query_key)
            if not raw_value:
                continue
            value = raw_value.strip()
            if not value:
                continue
            queryset = queryset.filter(**{model_field: value})

        # ── Column / status filter ───────────────────────────────────
        column_title = request.query_params.get("column_title")
        if column_title:
            queryset = queryset.filter(column__title__iexact=column_title)

        # Pagination uses DRF default (PageNumberPagination, 9/page).
        paginator = self.paginator
        page = paginator.paginate_queryset(queryset, request, view=self)
        serialized = [_serialize_finding(task) for task in (page or queryset)]
        if page is not None:
            return paginator.get_paginated_response(serialized)
        return Response(serialized)


_FINDINGS_FK_FILTERS = {
    "recipient_id": "recipient_id",
    "campaign_id": "campaign_id",
    "event_id": "event_id",
    "grant_id": "grant_id",
    "project_id": "project_id",
    "task_id": "id",
}


def _serialize_finding(task) -> dict:
    """Serialise a Task as an AI finding for the workspace widgets.

    Phase 5 of the Agents-as-Teammates migration deleted ``AIAction``.
    All agent attribution + detector context the frontend widgets read
    now lives on ``Task.description`` (narrative) and ``Task.metadata``
    (agent_type, detector, action_type, severity, impact_score,
    ai_headline, ai_narrative, idempotency_key, payload, context).
    """
    column = getattr(task, "column", None)
    return {
        "task_id": str(task.id),
        "title": task.title,
        "description": task.description or "",
        "source_type": task.source_type or "",
        "workspace_id": str(task.workspace_id) if task.workspace_id else None,
        "team_id": str(task.team_id) if task.team_id else None,
        "project_id": str(task.project_id) if task.project_id else None,
        "recipient_id": str(task.recipient_id) if task.recipient_id else None,
        "campaign_id": str(task.campaign_id) if task.campaign_id else None,
        "event_id": str(task.event_id) if task.event_id else None,
        "grant_id": str(task.grant_id) if task.grant_id else None,
        "column_id": str(column.id) if column else None,
        "column_title": column.title if column else "",
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "metadata": task.metadata or {},
    }


# ── Agent ViewSet ──
class AgentViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    # Restrict PK to UUIDs so /agents/shared/, /agents/executions/, /agents/teammate/
    # are not swallowed by the detail route /agents/{pk}/.
    lookup_value_regex = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

    # Social-discovery surfaces gated behind feature.agent_marketplace per the
    # GTM scope freeze. Execution, chat, memory, and workspace-admin actions
    # stay un-gated. See docs/plans/GTM_SCOPE_FREEZE_CHECKLIST.md entry 5.
    GATED_ACTIONS = frozenset({"follow", "like", "rate", "ratings", "comment", "comments", "share"})

    def get_permissions(self):
        if getattr(self, "action", None) in self.GATED_ACTIONS:
            self.feature_flag_key = "feature.agent_marketplace"
            return [IsAuthenticated(), RequiresFeatureFlag()]
        return super().get_permissions()

    @_schema(request_body=True)
    # create action
    def create(self, request):
        """Create a new AI agent - delegates to CreateAgentUseCase."""
        try:
            agent_type = request.data.get("agent_type")
            workspace_id = request.data.get("workspace_id")

            if not agent_type:
                return Response({"error": "agent_type is required"}, status=status.HTTP_400_BAD_REQUEST)
            if not workspace_id:
                return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)

            command = CreateAgentCommand(
                agent_type=agent_type,
                user_id=str(request.user.id),
                workspace_id=workspace_id,
                config=request.data.get("config", {}),
                department_id=request.data.get("department_id") or request.data.get("team_id"),
            )

            result = agents_service.create_agent(command)

            if isinstance(result, CreateAgentFailure):
                return Response({"error": result.error}, status=result.status_code)

            return Response({"success": True, "agent": result.agent_info}, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": f"Failed to create agent: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema()
    # list action
    def list(self, request):
        """List agents - delegates to ListAgentsQuery."""
        from components.agents.application.ports.agent_entitlement_port import ListAgentsRequest

        try:
            result = agents_service.list_agents(ListAgentsRequest(user_id=str(request.user.id)))
        except Exception as e:
            return Response({"error": f"Failed to list agents: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"agents": result.agents, "total": result.total}, status=status.HTTP_200_OK)

    @_schema()
    @action(detail=False, methods=["get"], url_path="types")
    def types(self, request):
        """List agent types - delegates to ListAgentTypesQuery."""
        from components.agents.application.ports.agent_entitlement_port import ListAgentTypesRequest

        try:
            result = agents_service.list_agent_types(
                ListAgentTypesRequest(
                    workspace_id=request.query_params.get("workspace_id"),
                    user=request.user,
                    include_inactive=_parse_bool(request.query_params.get("include_inactive")),
                    enabled_only=_parse_bool(request.query_params.get("enabled_only")),
                )
            )
        except (AgentNotFoundError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        except Exception as e:
            return Response(
                {"error": f"Failed to list agent types: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        return Response({"agent_types": result.agent_types, "total": result.total}, status=status.HTTP_200_OK)

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="types/entitlements")
    def entitlements(self, request):
        """Set agent entitlement - delegates to SetAgentEntitlementUseCase."""
        from components.agents.application.ports.agent_entitlement_port import SetEntitlementCommand

        try:
            result = agents_service.set_agent_entitlement(
                command=SetEntitlementCommand(
                    workspace_id=request.data.get("workspace_id", ""),
                    agent_type_slug=request.data.get("agent_type", ""),
                    is_enabled=request.data.get("is_enabled"),
                    user=request.user,
                ),
            )
        except (AgentNotFoundError, AgentPermissionError, AgentEngagementError) as exc:
            return _engagement_error_response(exc)
        return Response(
            {
                "workspace_id": result.workspace_id,
                "agent_type": result.agent_type,
                "is_enabled": result.is_enabled,
                "entitlement_id": result.entitlement_id,
            },
            status=status.HTTP_200_OK,
        )

    # ── Workspace AI Configuration ──────────────────────────────────────

    @_schema()
    @action(detail=False, methods=["get"], url_path="ai-config")
    def ai_config(self, request):
        """Get workspace AI configuration (model selection, persona limits, toggles)."""
        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from components.agents.application.providers.ai_provider import AIProvider

            port = AIProvider.build_workspace_ai_config_port()
            config = port.load(str(workspace_id))
            return Response({"workspace_id": workspace_id, "config": config.to_dict()}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"Failed to load AI config: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema(request_body=True)
    @action(detail=False, methods=["patch"], url_path="ai-config/update")
    def update_ai_config(self, request):
        """Update workspace AI configuration. Only workspace owner/admin can change."""
        workspace_id = request.data.get("workspace_id")
        if not workspace_id:
            return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from components.agents.application.providers.ai_provider import AIProvider
            from components.agents.domain.value_objects.workspace_ai_config import WorkspaceAIConfig

            port = AIProvider.build_workspace_ai_config_port()
            # Load existing, merge with incoming changes
            existing = port.load(str(workspace_id))
            existing_dict = existing.to_dict()
            incoming = request.data.get("config", {})
            if not isinstance(incoming, dict):
                return Response({"error": "config must be a JSON object"}, status=status.HTTP_400_BAD_REQUEST)
            existing_dict.update(incoming)
            updated_config = WorkspaceAIConfig.from_dict(existing_dict)
            port.save(str(workspace_id), updated_config)
            return Response(
                {"workspace_id": workspace_id, "config": updated_config.to_dict()}, status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response({"error": f"Failed to update AI config: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema()
    @action(detail=False, methods=["get"], url_path="ai-models")
    def ai_models(self, request):
        """List available AI models from the catalog. Workspace owners pick from these."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            AIModel = _pkg_models.AIModel
            provider_filter = request.query_params.get("provider")
            qs = AIModel.objects.filter(is_available=True).select_related("provider")
            if provider_filter:
                qs = qs.filter(provider__slug=provider_filter)
            models_list = [
                {
                    "slug": m.slug,
                    "name": m.name,
                    "provider": m.provider.slug,
                    "provider_name": m.provider.name,
                    "model_id": m.model_id,
                    "description": m.description,
                    "tier": m.tier,
                    "supports_streaming": m.supports_streaming,
                    "supports_tool_use": m.supports_tool_use,
                    "supports_vision": m.supports_vision,
                    "context_window": m.context_window,
                    "max_output_tokens": m.max_output_tokens,
                    "input_cost_per_1k": str(m.input_cost_per_1k),
                    "output_cost_per_1k": str(m.output_cost_per_1k),
                    "is_default": m.is_default,
                }
                for m in qs
            ]
            return Response({"models": models_list, "total": len(models_list)}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"Failed to list AI models: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema()
    @action(detail=False, methods=["get"], url_path="graph")
    def graph(self, request):
        """Return graph data for agent types, sessions, and lifetime activity.

        Phase 5 of the Agents-as-Teammates migration dropped the
        ``actions`` + ``action_counts`` fields here — AI findings are
        Kanban tasks now, read via ``/ai/findings/``.
        """
        from components.agents.application.ports.agent_graph_query_port import AgentGraphRequest

        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        normalized_workspace_id = str(ensure_uuid(workspace_id, field_name="workspace_id"))

        graph_request = AgentGraphRequest(
            workspace_id=normalized_workspace_id,
            agent_type_filter=request.query_params.get("agent_type"),
            include_inactive=_parse_bool(request.query_params.get("include_inactive")),
        )

        result = agents_service.agent_graph(graph_request, http_request=request)

        return Response(
            {
                "agent_types": result.agent_types,
                "sessions": result.sessions,
                "active_agent_types": result.active_agent_types,
                "agent_type_activity": result.agent_type_activity,
                "agent_instances": result.agent_instances,
            },
            status=status.HTTP_200_OK,
        )

    @_schema()
    # destroy action
    def destroy(self, request, pk=None):
        """Delete an agent - delegates to DeleteAgentUseCase."""
        result = agents_service.delete_agent(
            DeleteAgentCommand(agent_id=str(pk), user_id=str(request.user.id)),
        )
        if isinstance(result, DeleteAgentFailure):
            return Response({"error": result.error}, status=result.status_code)
        return Response({"success": True, "message": result.message}, status=status.HTTP_200_OK)

    @_schema(request_body=True)
    @action(detail=True, methods=["post"], url_path="execute")
    def execute(self, request, pk=None):
        """Execute a query with an AI agent - delegates to ExecuteAgentUseCase."""
        from components.agents.application.ports.agent_execution_command_port import ExecuteAgentCommand

        query = request.data.get("query")
        if not query:
            return Response({"error": "query is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = agents_service.execute_agent(
                command=ExecuteAgentCommand(
                    agent_id=str(pk),
                    query=query,
                    user_id=str(request.user.id),
                ),
            )
        except AiUnavailable as exc:
            return _ai_unavailable_response(exc)
        except AiRunLimitExceeded as exc:
            return _ai_run_limit_response(exc)
        except (AgentNotFoundError, AgentDisabledError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        except Exception as e:
            return Response({"error": f"Failed to execute agent: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        poll_url = request.build_absolute_uri(reverse("agents:get-agent-execution", args=[result.execution_id]))

        return Response(
            {
                "success": True,
                "agent_id": result.agent_id,
                "execution_id": result.execution_id,
                "task_id": result.task_id,
                "status": result.status,
                "progress": result.progress,
                "state": result.state,
                "conversation_id": result.conversation_id,
                "poll_url": poll_url,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @_schema()
    @action(detail=True, methods=["get"], url_path="state")
    def state(self, request, pk=None):
        """Get agent state - delegates to GetAgentStateQuery."""
        from components.agents.application.ports.agent_profile_port import GetAgentStateRequest

        try:
            data = agents_service.get_agent_state(
                GetAgentStateRequest(agent_id=str(pk), user_id=str(request.user.id)),
            )
        except (AgentNotFoundError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        except Exception as e:
            return Response(
                {"error": f"Failed to get agent state: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        return Response(
            {
                "agent_id": data.agent_id,
                "state": data.state,
                "profile": data.profile,
                "engagement_counts": data.engagement_counts,
                "is_disabled": data.is_disabled,
            },
            status=status.HTTP_200_OK,
        )

    @_schema()
    @action(detail=True, methods=["post"], url_path="pause")
    def pause(self, request, pk=None):
        """Pause an agent - delegates to AgentStateUseCase."""
        try:
            command = AgentStateCommand(
                agent_id=pk,
                user_id=str(request.user.id),
                action="pause",
            )
            result = agents_service.dispatch_agent_state(command)

            if isinstance(result, AgentStateFailure):
                return Response({"error": result.error}, status=result.status_code)

            return Response(
                {
                    "success": True,
                    "message": result.message,
                    "state": result.state,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response({"error": f"Failed to pause agent: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema()
    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, pk=None):
        """Resume an agent - delegates to AgentStateUseCase."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            Agent = _pkg_models.Agent
            agent_record = Agent.objects.select_related("profile").filter(agent_id=pk).first()
            if not agent_record:
                return Response({"error": "Agent not found"}, status=status.HTTP_404_NOT_FOUND)
            profile = getattr(agent_record, "profile", None)
            if profile and profile.is_disabled:
                return Response(
                    {"error": "Agent is disabled", "code": "agent_disabled"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            command = AgentStateCommand(
                agent_id=pk,
                user_id=str(request.user.id),
                action="resume",
            )
            result = agents_service.dispatch_agent_state(command)

            if isinstance(result, AgentStateFailure):
                return Response({"error": result.error}, status=result.status_code)

            return Response(
                {
                    "success": True,
                    "message": result.message,
                    "state": result.state,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response({"error": f"Failed to resume agent: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema()
    @action(detail=True, methods=["get"], url_path="profile")
    def profile(self, request, pk=None):
        """Get agent profile - delegates to GetAgentProfileQuery."""
        from components.agents.application.ports.agent_profile_port import GetAgentProfileRequest

        try:
            data = agents_service.get_agent_profile(
                GetAgentProfileRequest(agent_id=str(pk), user=request.user),
            )
        except (AgentNotFoundError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        return Response(
            {
                "agent_id": data.agent_id,
                "profile": data.profile,
                "engagement_counts": data.engagement_counts,
                "is_disabled": data.is_disabled,
            },
            status=status.HTTP_200_OK,
        )

    @_schema(request_body=True)
    @action(detail=True, methods=["patch"], url_path="profile/update")
    @throttle_classes([SettingsThrottle])
    def profile_update(self, request, pk=None):
        """Patch agent profile - delegates to PatchAgentProfileUseCase."""
        from components.agents.application.ports.agent_profile_port import PatchAgentProfileCommand

        try:
            result = agents_service.patch_agent_profile(
                command=PatchAgentProfileCommand(
                    agent_id=str(pk),
                    user=request.user,
                    data=request.data,
                    http_request=request,
                ),
            )
        except (AgentNotFoundError, AgentPermissionError, AgentEngagementError) as exc:
            return _engagement_error_response(exc)
        return Response(
            {
                "agent_id": result.agent_id,
                "profile": result.profile,
                "engagement_counts": result.engagement_counts,
                "is_disabled": result.is_disabled,
            },
            status=status.HTTP_200_OK,
        )

    @_schema(request_body=True)
    @action(detail=True, methods=["patch"], url_path="settings")
    @throttle_classes([SettingsThrottle])
    def update_settings(self, request, pk=None):
        """Update agent custom settings - delegates to PatchAgentSettingsUseCase."""
        from components.agents.application.ports.agent_profile_port import PatchAgentSettingsCommand

        try:
            result = agents_service.patch_agent_settings(
                command=PatchAgentSettingsCommand(
                    agent_id=str(pk),
                    user=request.user,
                    data=request.data or {},
                    http_request=request,
                ),
            )
        except (AgentNotFoundError, AgentPermissionError, AgentEngagementError) as exc:
            return _engagement_error_response(exc)
        return Response({"profile": result.profile}, status=status.HTTP_200_OK)

    @_schema(request_body=True)
    @action(detail=True, methods=["patch"], url_path="capabilities")
    @throttle_classes([SettingsThrottle])
    def update_capabilities(self, request, pk=None):
        """Toggle allowlisted, risk-gating agent capabilities (e.g. open_draft_pr).

        Separate from /settings/ on purpose: capabilities unlock risk-gated
        tools, so they carry their own strict allowlist in the repository.
        Body: {"open_draft_pr": true|false}.
        """
        from components.agents.application.ports.agent_profile_port import PatchAgentCapabilitiesCommand

        try:
            result = agents_service.patch_agent_capabilities(
                command=PatchAgentCapabilitiesCommand(
                    agent_id=str(pk),
                    user=request.user,
                    data=request.data or {},
                    http_request=request,
                ),
            )
        except (AgentNotFoundError, AgentPermissionError, AgentEngagementError) as exc:
            return _engagement_error_response(exc)
        return Response({"capabilities": result.capabilities}, status=status.HTTP_200_OK)

    @_schema(request_body=True)
    @action(
        detail=False,
        methods=["get", "post"],
        url_path="kill-switch",
        permission_classes=[IsAuthenticated, AiKillSwitchPermission],
    )
    def kill_switch(self, request):
        """Workspace AI kill switch (vision §3.4) — human-only, audited.

        GET  ?workspace_id=<uuid>              → current kill-switch status.
        POST {workspace_id, enabled, reason}   → flip Workspace.ai_teammate_enabled,
        write an audit entry (actor + reason + timestamp), return the new status.

        Owner/admin-gated for the flip (``manage_agents``); any member role
        may read the status (``view_agents``). Deliberately NOT an agent
        tool — the AI can report on the switch but never touch it.
        """
        from components.shared_kernel.domain.errors import NotFoundError, ValidationError

        if request.method == "GET":
            workspace_id = request.query_params.get("workspace_id")
            if not workspace_id:
                return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            data = agents_service.ai_kill_switch_status(workspace_id=str(workspace_id))
            return Response(data, status=status.HTTP_200_OK)

        workspace_id = request.data.get("workspace_id")
        enabled = request.data.get("enabled")
        reason = request.data.get("reason")
        if not workspace_id:
            return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(enabled, bool):
            return Response({"error": "enabled must be true or false"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = agents_service.set_ai_kill_switch(
                workspace_id=str(workspace_id),
                enabled=enabled,
                actor=request.user,
                reason=str(reason or ""),
            )
        except ValidationError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except NotFoundError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(data, status=status.HTTP_200_OK)

    @_schema()
    @action(
        detail=False,
        methods=["get"],
        url_path="posture/dashboard",
        permission_classes=[IsAuthenticated, PostureDashboardPermission],
    )
    def posture_dashboard(self, request):
        """Posture dashboard (HUD POSTURE module) — chart-ready series + KPI bands.

        GET ?workspace_id=<uuid>&persona=engineer|executive&window_days=<n>

        Read-only, membership-checked like the kill-switch GET
        (``view_agents``). Thin: parses params, calls ONE service front
        door, serialises. The response is composed from the existing
        aggregation services (posture, governance, log metrics) plus the
        ``AiActionDailyRollup`` read model — no composite score, every
        block carries a ``link`` drill hint.
        """
        from components.shared_kernel.domain.errors import ValidationError

        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        persona = request.query_params.get("persona") or "engineer"
        window_days = _parse_int(request.query_params.get("window_days"), default=7, min_value=1)
        try:
            data = agents_service.posture_dashboard(
                workspace_id=str(workspace_id),
                persona=str(persona),
                window_days=window_days,
            )
        except ValidationError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(data, status=status.HTTP_200_OK)

    @_schema()
    @action(detail=True, methods=["get"], url_path="memory")
    def memory(self, request, pk=None):
        """Get agent memory and conversation history."""
        from components.agents.application.ports.agent_execution_query_port import AgentMemoryRequest

        limit = _parse_int(request.GET.get("limit"), default=None, min_value=0)
        if limit == 0:
            limit = None
        offset = _parse_int(request.GET.get("offset"), default=0, min_value=0)
        order = request.GET.get("order", "asc").lower()
        if order not in {"asc", "desc"}:
            order = "asc"

        try:
            result = agents_service.agent_memory(
                AgentMemoryRequest(
                    agent_id=pk,
                    limit=limit,
                    offset=offset,
                    order=order,
                )
            )
        except LookupError:
            return Response({"error": "Agent not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"Failed to get agent memory: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not _has_agent_access(request.user, result.agent_record, include_followers=True):
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        return Response(
            {
                "memory_stats": result.memory_stats,
                "conversation_history": result.conversation_history,
                "agent_id": pk,
                "last_execution": result.last_execution,
                "last_progress": result.last_progress,
                "pagination": asdict(result.pagination),
            },
            status=status.HTTP_200_OK,
        )

    @_schema()
    @action(detail=True, methods=["post"], url_path="memory/clear")
    def memory_clear(self, request, pk=None):
        """Clear agent memory - delegates to ClearAgentMemoryUseCase."""
        from components.agents.application.ports.agent_memory_command_port import ClearMemoryCommand

        try:
            result = agents_service.clear_agent_memory(
                command=ClearMemoryCommand(agent_id=str(pk), user_id=str(request.user.id)),
            )
        except (AgentNotFoundError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        except Exception as e:
            return Response(
                {"error": f"Failed to clear agent memory: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        return Response({"message": result.message, "agent_id": result.agent_id}, status=status.HTTP_200_OK)

    @_schema(request_body=True)
    @action(detail=True, methods=["post"], url_path="memory/system-message")
    def memory_system_message(self, request, pk=None):
        """Add system message - delegates to AddAgentSystemMessageUseCase."""
        from components.agents.application.ports.agent_memory_command_port import AddSystemMessageCommand

        try:
            result = agents_service.add_system_message(
                command=AddSystemMessageCommand(
                    agent_id=str(pk),
                    user_id=str(request.user.id),
                    content=request.data.get("content", ""),
                ),
            )
        except (AgentNotFoundError, AgentPermissionError, AgentEngagementError) as exc:
            return _engagement_error_response(exc)
        except Exception as e:
            return Response(
                {"error": f"Failed to add system message: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        return Response(
            {"message": result.message, "agent_id": result.agent_id, "content": result.content},
            status=status.HTTP_200_OK,
        )

    @_schema()
    @action(detail=True, methods=["get"], url_path="executions")
    def executions(self, request, pk=None):
        """List executions for a specific agent with pagination."""
        from components.agents.application.ports.agent_execution_query_port import ExecutionListRequest

        limit = _parse_int(request.GET.get("limit"), default=50, min_value=0)
        if limit == 0:
            limit = None
        offset = _parse_int(request.GET.get("offset"), default=0, min_value=0)
        order = request.GET.get("order", "desc").lower()
        if order not in {"asc", "desc"}:
            order = "desc"

        try:
            result = agents_service.execution_list(
                ExecutionListRequest(
                    agent_id=pk,
                    limit=limit,
                    offset=offset,
                    order=order,
                    include_state=_parse_bool(request.GET.get("include_state")),
                )
            )
        except LookupError:
            return Response({"error": "Agent not found"}, status=status.HTTP_404_NOT_FOUND)

        if not _has_agent_access(request.user, result.agent_record, include_followers=True):
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        return Response(
            {
                "agent_id": result.agent_id,
                "executions": result.executions,
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "order": order,
                    "total": result.total,
                    "returned": result.returned,
                    "has_more": result.has_more,
                    "next_offset": result.next_offset,
                },
            },
            status=status.HTTP_200_OK,
        )

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="deep/run-plan")
    def deep_run_plan(self, request):
        """Execute a provided PlanSpec with an existing agent type - delegates to DeepRunPlanUseCase."""
        raw_plan = request.data.get("plan") or {}
        agent_type = request.data.get("agent_type") or "task_agent"
        workspace_id = request.data.get("workspace_id") or raw_plan.get("workspace_id")
        team_id = request.data.get("team_id") or raw_plan.get("team_id")
        thread_id = request.data.get("thread_id")

        if not workspace_id:
            return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        workspace = agents_service.get_workspace_by_id(workspace_id)
        if not workspace:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _has_teammate_permissions(request.user, workspace, include_followers=True):
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        from components.agents.domain.value_objects.plan_schemas import PlanSpec

        plan_id = raw_plan.get("plan_id") or request.data.get("plan_id") or str(uuid.uuid4())
        raw_plan["plan_id"] = plan_id
        raw_plan = default_plan_payload(raw_plan, str(workspace.id), team_id)

        try:
            validated_plan = PlanSpec.model_validate(raw_plan)
        except Exception as exc:
            return Response({"error": "Invalid plan", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        command = DeepRunPlanCommand(
            raw_plan=raw_plan,
            agent_type=agent_type,
            user_id=str(request.user.id),
            workspace_id=str(workspace.id),
            team_id=team_id,
            agent_config=request.data.get("agent_config") or {},
            thread_id=thread_id,
            sync_to_kanban=_parse_bool(request.data.get("sync_to_kanban", True)),
        )

        try:
            result = agents_service.deep_run_plan(command, validated_plan=validated_plan)
        except AiUnavailable as exc:
            return _ai_unavailable_response(exc)
        except AiRunLimitExceeded as exc:
            return _ai_run_limit_response(exc)

        if isinstance(result, DeepRunFailure):
            return Response({"error": result.error}, status=result.status_code)
        return Response({"plan_id": result.plan_id, "state": result.state}, status=status.HTTP_200_OK)

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="deep/plan-and-run")
    def deep_plan_and_run(self, request):
        """One-shot plan+execute - delegates to DeepPlanAndRunUseCase."""
        goal = request.data.get("goal")
        agent_type = request.data.get("agent_type") or "task_agent"
        workspace_id = request.data.get("workspace_id")
        team_id = request.data.get("team_id")

        if not goal or not workspace_id:
            return Response({"error": "goal and workspace_id are required"}, status=status.HTTP_400_BAD_REQUEST)

        workspace = agents_service.get_workspace_by_id(workspace_id)
        if not workspace:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _has_teammate_permissions(request.user, workspace, include_followers=True):
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        command = DeepPlanAndRunCommand(
            goal=goal,
            agent_type=agent_type,
            user_id=str(request.user.id),
            workspace_id=str(workspace.id),
            plan_id=request.data.get("plan_id") or "",
            team_id=team_id,
            agent_config=request.data.get("agent_config") or {},
            model_name=request.data.get("model_name"),
            sync_to_kanban=_parse_bool(request.data.get("sync_to_kanban", True)),
            extra_context=request.data.get("context"),
            deep_pack=request.data.get("deep_pack"),
        )

        try:
            result = agents_service.deep_plan_and_run(command)
        except AiUnavailable as exc:
            return _ai_unavailable_response(exc)
        except AiRunLimitExceeded as exc:
            return _ai_run_limit_response(exc)

        if isinstance(result, DeepRunFailure):
            return Response({"error": result.error}, status=result.status_code)
        return Response({"plan_id": result.plan_id, "state": result.state}, status=status.HTTP_200_OK)

    # ── Engagement actions (merged from AgentEngagementViewSet) ──────────

    @_schema()
    @action(detail=True, methods=["post", "delete"], url_path="follow")
    @throttle_classes([LikesThrottle])
    def follow(self, request, pk=None):
        """Follow (POST) or unfollow (DELETE) an agent."""
        if request.method == "DELETE":
            try:
                result = agents_service.unfollow_agent(
                    request=FollowRequest(agent_id=str(pk), user=request.user),
                )
            except AgentNotFoundError as exc:
                return _engagement_error_response(exc)
            return Response(
                {"following": result.following, "engagement_counts": asdict(result.engagement_counts)},
                status=status.HTTP_200_OK,
            )
        try:
            result = agents_service.follow_agent(
                request=FollowRequest(agent_id=str(pk), user=request.user),
            )
        except (AgentNotFoundError, AgentDisabledError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        return Response(
            {"following": result.following, "engagement_counts": asdict(result.engagement_counts)},
            status=status.HTTP_200_OK,
        )

    @_schema()
    @action(detail=True, methods=["post", "delete"], url_path="like")
    @throttle_classes([LikesThrottle])
    def like(self, request, pk=None):
        """Like (POST) or unlike (DELETE) an agent."""
        if request.method == "DELETE":
            try:
                result = agents_service.unlike_agent(
                    request=LikeRequest(agent_id=str(pk), user=request.user),
                )
            except AgentNotFoundError as exc:
                return _engagement_error_response(exc)
            return Response(
                {"liked": result.liked, "engagement_counts": asdict(result.engagement_counts)},
                status=status.HTTP_200_OK,
            )
        try:
            result = agents_service.like_agent(
                request=LikeRequest(agent_id=str(pk), user=request.user),
                http_request=request,
            )
        except (AgentNotFoundError, AgentDisabledError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        return Response(
            {"liked": result.liked, "engagement_counts": asdict(result.engagement_counts)}, status=status.HTTP_200_OK
        )

    @_schema(request_body=True)
    @action(detail=True, methods=["post"], url_path="rating")
    @throttle_classes([RatingsThrottle])
    def rate(self, request, pk=None):
        """Rate an agent - delegates to RateAgentUseCase."""
        try:
            result = agents_service.rate_agent(
                request=RateRequest(
                    agent_id=str(pk),
                    user=request.user,
                    score=request.data.get("score", 0),
                    comment=request.data.get("comment", ""),
                ),
                http_request=request,
            )
        except (AgentNotFoundError, AgentDisabledError, AgentPermissionError, AgentEngagementError) as exc:
            return _engagement_error_response(exc)
        return Response(
            {"rated": result.rated, "engagement_counts": asdict(result.engagement_counts)}, status=status.HTTP_200_OK
        )

    @_schema()
    @action(detail=True, methods=["get"], url_path="ratings")
    def ratings(self, request, pk=None):
        """Paginated ratings - delegates to FetchAgentRatingsQuery."""
        try:
            data = agents_service.agent_ratings(
                ListRatingsRequest(agent_id=str(pk), user=request.user),
                http_request=request,
            )
        except (AgentNotFoundError, AgentDisabledError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        return Response(
            {"count": data.count, "next": data.next_url, "previous": data.previous_url, "results": data.ratings}
        )

    @_schema(request_body=True)
    @action(detail=True, methods=["post"], url_path="comments/create")
    @throttle_classes([CommentsThrottle])
    def comment(self, request, pk=None):
        """Add comment - delegates to CommentAgentUseCase."""
        try:
            result = agents_service.comment_agent(
                request=CommentRequest(
                    agent_id=str(pk),
                    user=request.user,
                    body=request.data.get("body", ""),
                    parent_id=request.data.get("parent"),
                ),
                http_request=request,
            )
        except (
            AgentNotFoundError,
            AgentDisabledError,
            AgentPermissionError,
            AgentEngagementError,
            InvalidCommentError,
        ) as exc:
            return _engagement_error_response(exc)
        return Response(
            {"commented": result.commented, "engagement_counts": asdict(result.engagement_counts)},
            status=status.HTTP_201_CREATED,
        )

    @_schema()
    @action(detail=True, methods=["get"], url_path="comments")
    def comments(self, request, pk=None):
        """Paginated comments with replies - delegates to FetchAgentCommentsQuery."""
        try:
            data = agents_service.agent_comments(
                ListCommentsRequest(agent_id=str(pk), user=request.user),
                http_request=request,
            )
        except (AgentNotFoundError, AgentDisabledError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        return Response(
            {"count": data.count, "next": data.next_url, "previous": data.previous_url, "results": data.comments}
        )

    @_schema(request_body=True)
    @action(detail=True, methods=["post"], url_path="share")
    @throttle_classes([SharesThrottle])
    def share(self, request, pk=None):
        """Create share token - delegates to ShareAgentUseCase."""
        try:
            result = agents_service.share_agent(
                request=ShareRequest(
                    agent_id=str(pk),
                    user=request.user,
                    scope=request.data.get("scope", ""),
                    expires_at=request.data.get("expires_at"),
                ),
                http_request=request,
            )
        except (AgentNotFoundError, AgentPermissionError, InvalidShareScopeError) as exc:
            return _engagement_error_response(exc)
        return Response({"share": result.share_data, "share_url": result.share_url}, status=status.HTTP_201_CREATED)


# ── Shared Agent ViewSet ──
class SharedAgentViewSet(viewsets.GenericViewSet):
    # Shared-agent access is part of the agent marketplace social layer —
    # gated behind feature.agent_marketplace per GTM scope freeze.
    permission_classes = [RequiresFeatureFlag]
    feature_flag_key = "feature.agent_marketplace"

    @_schema()
    # retrieve/destroy action
    def shared_agent(self, request, pk=None):
        """Fetch (GET) or revoke (DELETE) a shared agent by share token."""
        if request.method == "DELETE":
            try:
                result = agents_service.revoke_share(
                    request=RevokeShareRequest(share_token=pk, user=request.user),
                    http_request=request,
                )
            except (ShareNotFoundError, AgentPermissionError) as exc:
                return _engagement_error_response(exc)
            return Response({"revoked": result.revoked}, status=status.HTTP_200_OK)
        try:
            data = agents_service.shared_agent(
                GetSharedAgentRequest(share_token=pk, user=request.user),
            )
        except (ShareNotFoundError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)
        return Response(
            {
                "agent_id": data.agent_id,
                "profile": data.profile,
                "engagement_counts": data.engagement_counts,
                "is_disabled": data.is_disabled,
            },
            status=status.HTTP_200_OK,
        )


# ── Agent Execution ViewSet ──
class AgentExecutionViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @_schema()
    # retrieve action
    def retrieve(self, request, pk=None):
        """Get the latest status for a specific agent execution."""
        from components.agents.application.ports.agent_execution_query_port import ExecutionDetailRequest

        limit = _parse_int(request.GET.get("limit"), default=None, min_value=0)
        if limit == 0:
            limit = None
        offset = _parse_int(request.GET.get("offset"), default=0, min_value=0)
        order = request.GET.get("order", "asc").lower()
        if order not in {"asc", "desc"}:
            order = "asc"

        try:
            result = agents_service.execution_detail(
                ExecutionDetailRequest(
                    execution_id=pk,
                    limit=limit,
                    offset=offset,
                    order=order,
                )
            )
        except LookupError:
            return Response({"error": "Execution not found"}, status=status.HTTP_404_NOT_FOUND)

        if not _has_agent_access(request.user, result.agent_record, include_followers=True):
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        data = {
            "execution_id": result.execution_id,
            "agent_id": result.agent_id,
            "task_id": result.task_id,
            "status": result.status,
            "success": result.success,
            "progress": result.progress,
            "state": result.state,
            "result": result.result,
            "error_message": result.error_message,
            "created_at": result.created_at,
            "updated_at": result.updated_at,
            "conversation_id": result.conversation_id,
            "conversation_messages": result.conversation_messages,
            "conversation_pagination": asdict(result.conversation_pagination),
        }
        return Response(data, status=status.HTTP_200_OK)


# ── Deep Run Observability ViewSet ──
class DeepRunViewSet(viewsets.GenericViewSet):
    """Read-only observability endpoints for deep-agent runs.

    Routed at ``/ai/agents/runs/`` — see ``urls.py``.  The frontend uses
    these to render the progress bar, sub-agent tree, and dashboard
    stats once a chat run has kicked off.
    """

    permission_classes = [IsAuthenticated]

    @_schema()
    def retrieve(self, request, pk=None):
        """``GET /ai/agents/runs/<plan_id>/`` — snapshot for one run."""
        from components.agents.api.resources.deep_run_observability_resource import (
            DeepRunSnapshotResource,
        )
        from components.agents.application.providers.ai_provider import AIProvider

        query = AIProvider.build_deep_run_snapshot_query()
        view = query.execute(pk)
        if view is None:
            return Response({"error": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        if view.user_id != str(request.user.id) and not request.user.is_staff:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        return Response(DeepRunSnapshotResource.from_view(view).to_dict())

    @_schema()
    @action(detail=True, methods=["get"], url_path="events")
    def events(self, request, pk=None):
        """``GET /ai/agents/runs/<plan_id>/events/?since=<iso>&limit=<n>``."""
        from django.utils.dateparse import parse_datetime

        from components.agents.api.resources.deep_run_observability_resource import (
            DeepRunEventResource,
        )
        from components.agents.application.providers.ai_provider import AIProvider

        snapshot_query = AIProvider.build_deep_run_snapshot_query()
        snapshot = snapshot_query.execute(pk)
        if snapshot is None:
            return Response({"error": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        if snapshot.user_id != str(request.user.id) and not request.user.is_staff:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        since_raw = request.GET.get("since")
        since = parse_datetime(since_raw) if since_raw else None
        limit = _parse_int(request.GET.get("limit"), default=200, min_value=1)
        limit = min(limit, 500)

        query = AIProvider.build_deep_run_events_query()
        events = query.execute(pk, since=since, limit=limit)
        return Response(
            {
                "events": [DeepRunEventResource.from_view(e).to_dict() for e in events],
            }
        )

    @_schema()
    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """``GET /ai/agents/runs/stats/?workspace_id=<id>&since=<iso>``."""
        from django.utils.dateparse import parse_datetime

        from components.agents.api.resources.deep_run_observability_resource import (
            DeepRunStatsResource,
        )
        from components.agents.application.providers.ai_provider import AIProvider

        workspace_id = request.GET.get("workspace_id") or None
        if workspace_id:
            workspace = agents_service.get_workspace_by_id(workspace_id)
            if not workspace:
                return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
            if not _has_teammate_permissions(request.user, workspace):
                return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        elif not request.user.is_staff:
            return Response(
                {"error": "workspace_id is required unless you are staff."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        since_raw = request.GET.get("since")
        since = parse_datetime(since_raw) if since_raw else None

        query = AIProvider.build_deep_run_stats_query()
        view = query.execute(workspace_id, since=since)
        return Response(DeepRunStatsResource.from_view(view).to_dict())

    @action(detail=False, methods=["get"], url_path="analytics/overview")
    def analytics_overview(self, request):
        """``GET /ai/agents/runs/analytics/overview/?workspace_id=<id>&days=30``.

        Day-bucketed AI quality series (per-model calls/tokens/cost/latency,
        run outcomes, thumbs up/down) plus model-switch annotations, read from
        the pre-computed rollups the hourly beat task maintains.
        """
        from components.agents.api.resources.ai_quality_resources import (
            AIQualityOverviewResource,
        )
        from components.agents.application.providers.ai_provider import AIProvider

        workspace_id = request.GET.get("workspace_id") or None
        if not workspace_id:
            return Response(
                {"error": "workspace_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        workspace = agents_service.get_workspace_by_id(workspace_id)
        if not workspace:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _has_teammate_permissions(request.user, workspace):
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        try:
            days = int(request.GET.get("days", 30))
        except (TypeError, ValueError):
            return Response(
                {"error": "days must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        query = AIProvider.build_ai_quality_overview_query()
        view = query.execute(workspace_id, days=days)
        return Response(AIQualityOverviewResource.from_view(view).to_dict())


# ── Teammate ViewSet ──
class TeammateViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @_schema(request_body=True)
    def retrieve(self, request, pk=None):
        return self.teammate_profile(request, pk)

    @_schema(request_body=True)
    def partial_update(self, request, pk=None):
        return self.teammate_profile(request, pk)

    def teammate_profile(self, request, pk=None):
        """Retrieve or update teammate profile - delegates to use cases."""
        from components.agents.application.ports.teammate_profile_port import (
            GetTeammateProfileRequest,
            UpdateTeammateProfileCommand,
        )

        try:
            if request.method == "GET":
                data = agents_service.get_teammate_profile(
                    GetTeammateProfileRequest(workspace_id=str(pk), user=request.user),
                )
                return Response(
                    {
                        "workspace_id": data.workspace_id,
                        "display_name": data.display_name,
                        "avatar_url": data.avatar_url,
                    },
                    status=status.HTTP_200_OK,
                )

            raw_avatar = request.data.get("avatar_url")
            result = agents_service.update_teammate_profile(
                command=UpdateTeammateProfileCommand(
                    workspace_id=str(pk),
                    user=request.user,
                    display_name=request.data.get("display_name"),
                    # Absent key = leave the avatar untouched; "" = clear it.
                    avatar_url=str(raw_avatar) if raw_avatar is not None else None,
                ),
            )
            return Response(
                {
                    "workspace_id": result.workspace_id,
                    "display_name": result.display_name,
                    "avatar_url": result.avatar_url,
                },
                status=status.HTTP_200_OK,
            )
        except (AgentNotFoundError, AgentPermissionError) as exc:
            return _engagement_error_response(exc)


# ── Conversation ViewSet ──
class ConversationViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @_schema()
    # list action
    def list(self, request):
        """List PDF conversations."""
        try:
            pdf_id = request.query_params.get("pdf_id")
            workspace_id = request.query_params.get("workspace_id")

            conversations = agents_service.list_conversations_for_user(request.user)

            if pdf_id and workspace_id:
                conversations = conversations.filter(metadata__pdf_id=pdf_id, metadata__workspace_id=workspace_id)
            elif pdf_id:
                conversations = conversations.filter(metadata__pdf_id=pdf_id)
            elif workspace_id:
                conversations = conversations.filter(metadata__workspace_id=workspace_id)

            # Hide internal deep-agent "Run Context" conversations —
            # they're scratchpads for sub-agent memory during a deep
            # run, not user-facing chats.  ``__contains`` generates the
            # ``@>`` JSONB operator, which only matches when the key
            # is present AND equals True (unlike ``metadata__internal=True``
            # which silently drops rows where the key is absent).
            conversations = conversations.exclude(metadata__contains={"internal": True})

            conversations = conversations.order_by("-updated_at")
            serializer = ConversationListSerializer(conversations, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {"error": f"Failed to list conversations: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema(request_body=True)
    # create action
    def create(self, request):
        """Create a PDF conversation."""
        try:
            serializer = CreateConversationSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            pdf_id = serializer.validated_data["pdf_id"]
            workspace_id = serializer.validated_data.get("workspace_id")
            title = serializer.validated_data.get("title", f"Conversation about document {pdf_id}")

            if not workspace_id:
                return Response(
                    {"error": "workspace_id is required for conversation creation"}, status=status.HTTP_400_BAD_REQUEST
                )

            from components.shared_platform.application.providers.uploads_models_provider import (
                get_uploads_models_provider,
            )

            _pkg_models = get_uploads_models_provider()
            File = _pkg_models.File
            document = get_object_or_404(File, id=pdf_id)

            # Chat retrieval reads the document's indexed chunks — indexing
            # is OPT-IN, so an un-indexed document has nothing to retrieve
            # and the conversation would answer from thin air. Refuse with
            # the action the user needs to take.
            if document.processing_status != "completed":
                return Response(
                    {
                        "error": "Index this document to chat about it.",
                        "code": "document_not_indexed",
                        "processing_status": document.processing_status,
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            conversation = agents_service.create_conversation(
                user=request.user, title=title, metadata={"pdf_id": pdf_id, "workspace_id": workspace_id}
            )

            response_serializer = ConversationSerializer(conversation)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"error": f"Failed to create conversation: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema()
    # retrieve action
    def retrieve(self, request, pk=None):
        """Get PDF conversation details."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            Conversation = _pkg_models.Conversation
            conversation = get_object_or_404(Conversation, id=pk, user=request.user)
            serializer = ConversationSerializer(conversation)
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {"error": f"Failed to get conversation: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema(request_body=True)
    # partial_update action — rename title (editable from the chat UI)
    def partial_update(self, request, pk=None):
        """Rename a conversation. Only the owner can rename."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            Conversation = _pkg_models.Conversation
            conversation = get_object_or_404(Conversation, id=pk, user=request.user)
            new_title = request.data.get("title")
            if new_title is None:
                return Response(
                    {"error": "title is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            normalized_title = str(new_title).strip()
            if not normalized_title:
                return Response(
                    {"error": "title cannot be blank"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if normalized_title != conversation.title:
                conversation.title = normalized_title
                conversation.save(update_fields=["title", "updated_at"])
            serializer = ConversationSerializer(conversation)
            return Response(serializer.data)
        except Exception:
            logger.exception("partial_update conversation failed pk=%s", pk)
            return Response(
                {"error": "Failed to rename conversation"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @_schema()
    # destroy action
    def destroy(self, request, pk=None):
        """Delete a PDF conversation."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            Conversation = _pkg_models.Conversation
            conversation = get_object_or_404(Conversation, id=pk, user=request.user)
            agents_service.delete_conversation(conversation.id, user=request.user)
            return Response({"message": "Conversation deleted successfully", "conversation_id": str(pk)})
        except Exception as e:
            return Response(
                {"error": f"Failed to delete conversation: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema()
    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request, pk=None):
        """Get conversation messages."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            Conversation = _pkg_models.Conversation
            conversation = get_object_or_404(Conversation, id=pk, user=request.user)
            messages = conversation.messages.all().order_by("created_at").prefetch_related("feedback")
            serializer = ConversationMessageSerializer(messages, many=True, context={"request": request})
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": f"Failed to get messages: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema(request_body=True)
    @action(detail=True, methods=["post"], url_path="messages/create")
    def create_message(self, request, pk=None):
        """Send a message in a PDF conversation - delegates to PdfChatUseCase."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            Conversation = _pkg_models.Conversation
            conversation = get_object_or_404(Conversation, id=pk, user=request.user)

            serializer = CreateMessageSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            input_text = serializer.validated_data["input"]
            streaming = request.query_params.get("stream", "false").lower() == "true"

            pdf_id = conversation.metadata.get("pdf_id")
            workspace_id = conversation.metadata.get("workspace_id")

            conversation.messages.create(role="human", content=input_text)

            if not pdf_id or not workspace_id:
                response_content = f"I received your message: '{input_text}'. However, I " + (
                    "don't have access to any document content to provide context-specific answers."
                    if not pdf_id
                    else "need a workspace context to provide accurate answers about your document content."
                )
            else:
                recent_messages = conversation.messages.all().order_by("-created_at")[:6]
                chat_history = []
                for msg in reversed(recent_messages):
                    prefix = "Human: " if msg.role == "human" else "Assistant: "
                    chat_history.append(prefix + msg.content)

                command = PdfChatCommand(
                    conversation_id=UUID(str(conversation.id)),
                    user_id=UUID(str(request.user.id)),
                    pdf_id=str(pdf_id),
                    workspace_id=str(workspace_id),
                    query=input_text,
                    chat_history=chat_history,
                )

                result = agents_service.pdf_chat(command)

                if isinstance(result, PdfChatSuccess):
                    response_content = result.content
                elif isinstance(result, PdfChatNoContent):
                    return Response(
                        {"error": result.error, "pdf_id": result.pdf_id, "workspace_id": result.workspace_id},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                elif isinstance(result, PdfChatNoRelevantDocs):
                    response_content = (
                        f"I couldn't find any relevant information in document {pdf_id} "
                        f"for workspace {workspace_id}. Please make sure the document has "
                        "been processed and contains content related to your question."
                    )
                else:
                    response_content = f"I encountered an error: {result.error}"

            if streaming:

                def generate_stream():
                    try:
                        assistant_message = conversation.messages.create(role="assistant", content="")
                        yield f"data: {json.dumps({'token': response_content, 'type': 'token'})}\n\n"
                        assistant_message = agents_service.update_message_streaming(
                            assistant_message, content=response_content, is_streaming=False
                        )
                        yield f"data: {json.dumps({'type': 'complete', 'message_id': str(assistant_message.id)})}\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

                return StreamingHttpResponse(
                    generate_stream(),
                    content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
                )

            assistant_message = conversation.messages.create(role="assistant", content=response_content)
            return Response(
                {
                    "role": "assistant",
                    "content": response_content,
                    "message_id": str(assistant_message.id),
                    "conversation_id": str(conversation.id),
                }
            )
        except Exception as e:
            return Response({"error": f"Failed to create message: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema(request_body=True)
    def partial_update(self, request, pk=None):
        """Rename a conversation (PATCH ``title``)."""
        from components.agents.application.providers.ai_models_provider import (
            get_ai_models_provider,
        )

        _pkg_models = get_ai_models_provider()
        Conversation = _pkg_models.Conversation

        conversation = get_object_or_404(Conversation, id=pk, user=request.user)
        raw = request.data.get("title")
        if raw is None:
            return Response(
                {"error": "title is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        title = str(raw).strip()
        if not title:
            return Response(
                {"error": "title must not be empty"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        conversation.title = title[:200]
        conversation.save(update_fields=["title", "updated_at"])
        serializer = ConversationSerializer(conversation)
        return Response(serializer.data)

    @_schema(request_body=True)
    @action(
        detail=True,
        methods=["post", "delete"],
        url_path=r"messages/(?P<message_id>[^/.]+)/feedback",
    )
    def message_feedback(self, request, pk=None, message_id=None):
        """Record or remove a thumbs-up / thumbs-down on an assistant message.

        POST body: ``{"rating": "up" | "down", "comment": "optional"}``
        DELETE removes the current user's feedback on the message.
        Only one feedback per (user, message); POST upserts.
        """
        from components.agents.application.providers.ai_models_provider import (
            get_ai_models_provider,
        )

        _pkg_models = get_ai_models_provider()
        AgentResponseFeedback = _pkg_models.AgentResponseFeedback
        Conversation = _pkg_models.Conversation
        ConversationMessage = _pkg_models.ConversationMessage

        conversation = get_object_or_404(Conversation, id=pk, user=request.user)
        message = get_object_or_404(
            ConversationMessage,
            id=message_id,
            conversation=conversation,
        )
        if message.role != "assistant":
            return Response(
                {"error": "Feedback can only be attached to assistant messages."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        def _aggregate_counts():
            from components.shared_kernel.application.providers.django_orm_provider import (
                get_django_orm_provider as _get_django_orm_provider,
            )

            _django_orm = _get_django_orm_provider()
            Count = _django_orm.Count
            rows = AgentResponseFeedback.objects.filter(message=message).values("rating").annotate(n=Count("id"))
            counts = {"up": 0, "down": 0}
            for row in rows:
                if row["rating"] in counts:
                    counts[row["rating"]] = row["n"]
            return counts

        if request.method == "DELETE":
            AgentResponseFeedback.objects.filter(message=message, user=request.user).delete()
            return Response(
                {
                    "removed": True,
                    "message_id": str(message.id),
                    "conversation_id": str(conversation.id),
                    "my_feedback": None,
                    "feedback_counts": _aggregate_counts(),
                },
                status=status.HTTP_200_OK,
            )

        rating = (request.data.get("rating") or "").strip().lower()
        if rating not in ("up", "down"):
            return Response(
                {"error": "rating must be 'up' or 'down'"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        comment = (request.data.get("comment") or "").strip()[:2000]

        feedback, created = AgentResponseFeedback.objects.update_or_create(
            message=message,
            user=request.user,
            defaults={"rating": rating, "comment": comment},
        )
        return Response(
            {
                "id": str(feedback.id),
                "message_id": str(message.id),
                "conversation_id": str(conversation.id),
                "rating": feedback.rating,
                "my_feedback": feedback.rating,
                "comment": feedback.comment,
                "created": created,
                "feedback_counts": _aggregate_counts(),
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


# ── Chat ViewSet ──
class ChatViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="pdf-search")
    def pdf_search(self, request):
        """Search PDF content."""
        try:
            query = request.data.get("query", "")
            pdf_id = request.data.get("pdf_id")
            workspace_id = request.data.get("workspace_id")
            k = request.data.get("k", 10)

            if not query:
                return Response({"error": "Query is required"}, status=status.HTTP_400_BAD_REQUEST)
            if not pdf_id:
                return Response({"error": "pdf_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            if not workspace_id:
                return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)

            from components.agents.application.providers.retrieval_chain_provider import (
                get_retrieval_chain_provider,
            )

            _retrieval_provider_local = get_retrieval_chain_provider()
            _s = _retrieval_provider_local.normalize_metadata_value
            _has_indexed_chunks = _retrieval_provider_local.has_indexed_chunks

            retriever = agents_service.get_vector_store_port().search(
                query=query,
                k=k,
                filters={"pdf_id": str(pdf_id), "workspace_id": str(workspace_id), "user_id": str(request.user.id)},
            )

            if not _has_indexed_chunks(retriever, pdf_id, workspace_id, request.user.id):
                return Response(
                    {
                        "error": f"No content found for document {pdf_id} in workspace {workspace_id}. Please make sure the document has been processed.",
                        "pdf_id": pdf_id,
                        "workspace_id": workspace_id,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            relevant_docs = retriever.get_relevant_documents(query)

            pdf_docs = [
                doc
                for doc in relevant_docs
                if (
                    doc.metadata.get("pdf_id") == _s(pdf_id)
                    and doc.metadata.get("user_id") == _s(request.user.id)
                    and doc.metadata.get("workspace_id") == _s(workspace_id)
                )
            ]

            return Response(
                {
                    "query": query,
                    "pdf_id": pdf_id,
                    "workspace_id": workspace_id,
                    "relevant_docs_count": len(relevant_docs),
                    "pdf_docs_count": len(pdf_docs),
                    "docs": [
                        {"content": doc.page_content[:200] + "...", "metadata": doc.metadata} for doc in pdf_docs[:3]
                    ],
                }
            )

        except Exception as e:
            return Response(
                {"error": f"Failed to search document content: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema()
    @action(detail=False, methods=["get"], url_path="pdf-diagnose")
    def pdf_diagnose(self, request):
        """Diagnostic endpoint to check document processing status and vector store content."""
        try:
            pdf_id = request.query_params.get("pdf_id")
            workspace_id = request.query_params.get("workspace_id")
            reprocess = request.query_params.get("reprocess", "false").lower() == "true"

            if not pdf_id:
                return Response({"error": "pdf_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            if not workspace_id:
                return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)

            from components.shared_platform.application.providers.uploads_models_provider import (
                get_uploads_models_provider,
            )

            _pkg_models = get_uploads_models_provider()
            File = _pkg_models.File
            file_obj = None
            try:
                file_obj = agents_service.get_file_by_id(pdf_id, request.user)
                file_status = {
                    "id": file_obj.id,
                    "file_name": file_obj.file.name,
                    "file_type": file_obj.file_type,
                    "processing_status": file_obj.processing_status,
                    "processed_at": file_obj.processed_at,
                    "processing_error": file_obj.processing_error,
                    "workspace_id": file_obj.workspace_id,
                    "created": file_obj.created,
                }
            except File.DoesNotExist:
                file_status = {"error": "File not found or not owned by user"}

            reprocess_result = None
            if reprocess:
                if not file_obj:
                    reprocess_result = {"success": False, "error": "File not found or not owned by user"}
                elif file_obj.file_type not in ("pdf", "document"):
                    reprocess_result = {"success": False, "error": "File is not a supported document"}
                else:
                    try:
                        embeddings_result = _run_embedding_for_file(
                            file_obj=file_obj,
                            pdf_id=pdf_id,
                            workspace_id=workspace_id,
                            user_id=request.user.id,
                        )

                        if embeddings_result["success"]:
                            file_obj.processing_status = "completed"
                            file_obj.processed_at = timezone.now()
                            file_obj.processing_error = None
                            agents_service.update_file_status(file_obj, status="completed")

                            reprocess_result = {
                                "success": True,
                                "message": "Document reprocessed successfully",
                                "embeddings_result": embeddings_result,
                            }
                        else:
                            file_obj.processing_status = "failed"
                            file_obj.processing_error = embeddings_result.get("error", "Unknown error")
                            agents_service.update_file_status(file_obj, status="failed")

                            reprocess_result = {
                                "success": False,
                                "error": f"Document reprocessing failed: {embeddings_result.get('error', 'Unknown error')}",
                                "embeddings_result": embeddings_result,
                            }
                    except Exception as e:
                        reprocess_result = {"success": False, "error": f"Reprocessing failed: {e!s}"}

            try:
                from components.agents.application.providers.retrieval_chain_provider import (
                    get_retrieval_chain_provider,
                )

                _retrieval_provider_local = get_retrieval_chain_provider()
                _s = _retrieval_provider_local.normalize_metadata_value
                _has_indexed_chunks = _retrieval_provider_local.has_indexed_chunks

                retriever = agents_service.get_vector_store_port().search(
                    query=" ",
                    k=10,
                    filters={"pdf_id": str(pdf_id), "workspace_id": str(workspace_id), "user_id": str(request.user.id)},
                )

                has_chunks = _has_indexed_chunks(retriever, pdf_id, workspace_id, request.user.id)

                sample_docs = retriever if isinstance(retriever, list) else [retriever]
                pdf_docs = [
                    doc
                    for doc in sample_docs
                    if (
                        doc.metadata.get("pdf_id") == _s(pdf_id)
                        and doc.metadata.get("user_id") == _s(request.user.id)
                        and doc.metadata.get("workspace_id") == _s(workspace_id)
                    )
                ]

                vector_status = {
                    "has_chunks": has_chunks,
                    "total_sample_docs": len(sample_docs),
                    "pdf_docs_found": len(pdf_docs),
                    "sample_metadata": [doc.metadata for doc in pdf_docs[:3]] if pdf_docs else [],
                }
            except Exception as e:
                vector_status = {"error": f"Vector store check failed: {e!s}"}

            return Response(
                {
                    "pdf_id": pdf_id,
                    "workspace_id": workspace_id,
                    "user_id": str(request.user.id),
                    "file_status": file_status,
                    "vector_status": vector_status,
                    "reprocess_result": reprocess_result,
                }
            )

        except Exception as e:
            return Response({"error": f"Diagnostic failed: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="pdf-summarize")
    def pdf_summarize(self, request):
        """Generate a standalone PDF summary - delegates to PdfSummaryUseCase."""
        try:
            pdf_id = request.data.get("pdf_id")
            workspace_id = request.data.get("workspace_id")
            max_length = request.data.get("max_length", 500)

            if not pdf_id:
                return Response({"error": "pdf_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            if not workspace_id:
                return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)

            command = PdfSummaryCommand(
                pdf_id=str(pdf_id),
                workspace_id=str(workspace_id),
                user_id=str(request.user.id),
                max_length=max_length,
            )

            result = agents_service.pdf_summary(command)

            if isinstance(result, PdfSummaryNoContent):
                return Response(
                    {"error": result.error, "pdf_id": result.pdf_id, "workspace_id": result.workspace_id},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if isinstance(result, PdfSummaryFailure):
                return Response(
                    {"error": result.error},
                    status=getattr(result, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR),
                )

            return Response(
                {
                    "pdf_id": pdf_id,
                    "workspace_id": workspace_id,
                    "summary": result.summary,
                    "total_chunks": result.total_chunks,
                    "word_count": result.word_count,
                    "max_length": result.max_length,
                }
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to summarize document: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="agent-chat")
    def agent_chat(self, request):
        """Unified chat endpoint — every message runs through the deep-agent pipeline.

        Request body::

            {
                "query": "tldr this workspace",
                "workspace_id": "<uuid>",
                "conversation_id": "<uuid>?",
                "agent_type": "workspace_agent?",
                "persona_role": "contributor?"
            }

        Replaces the legacy ``/chat/workspace-chat/`` endpoint.  There is
        no keyword router, no direct-handler short-circuit, and no
        embedding fallback shim — the deep agent plans with retrieved
        workspace context and produces a grounded answer.
        """
        query = (request.data.get("query") or "").strip()
        workspace_id = request.data.get("workspace_id")

        if not query:
            return Response({"error": "Query is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not workspace_id:
            return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        workspace = agents_service.get_workspace_by_id(workspace_id)
        if not workspace:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _has_teammate_permissions(request.user, workspace):
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        # Optional client-supplied plan_id. See AgentChatCommand.plan_id
        # for the rationale — short version: the chat UI uses this to
        # open a WebSocket on ``agent_run/<plan_id>`` before the
        # orchestrator starts, so log/progress events from inside tools
        # stream live into the tool-call card. Validated as a UUID
        # before the use case sees it; an invalid value is treated as
        # "client didn't send one" so we don't 400 a chat request over
        # an instrumentation field.
        client_plan_id = request.data.get("plan_id")
        try:
            client_plan_id = UUID(str(client_plan_id)) if client_plan_id else None
        except (ValueError, TypeError):
            client_plan_id = None

        try:
            command = AgentChatCommand(
                query=query,
                workspace_id=workspace_id,
                user_id=request.user.id,
                user_email=getattr(request.user, "email", "") or "",
                username=getattr(request.user, "username", "") or "",
                user_full_name=(
                    f"{getattr(request.user, 'first_name', '')} {getattr(request.user, 'last_name', '')}"
                ).strip(),
                persona_role=request.data.get("persona_role") or "",
                conversation_id=request.data.get("conversation_id"),
                agent_type=request.data.get("agent_type") or "workspace_agent",
                plan_id=client_plan_id,
            )
            result = agents_service.agent_chat(command)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("agent_chat failed")
            return Response(
                {"error": f"Agent chat failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if isinstance(result, AgentChatSuccess):
            return Response(AgentChatResource.from_success(result).to_dict())

        assert isinstance(result, AgentChatFailure)
        return Response(
            AgentChatErrorResource.from_failure(result).to_dict(),
            status=result.status_code or status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="workspace-search")
    def workspace_search(self, request):
        """Search workspace content."""
        try:
            query = request.data.get("query")
            workspace_id = request.data.get("workspace_id")
            k = request.data.get("k", 5)

            if not query:
                return Response({"error": "Query is required"}, status=status.HTTP_400_BAD_REQUEST)
            if not workspace_id:
                return Response({"error": "workspace_id is required"}, status=status.HTTP_400_BAD_REQUEST)

            workspace = agents_service.get_workspace_by_id(workspace_id)
            if not workspace:
                return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
            if not _has_teammate_permissions(request.user, workspace):
                return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

            search_request = WorkspaceSearchRequest(
                query=query,
                workspace_id=str(workspace_id),
                user_id=str(request.user.id),
                k=k,
            )

            result = agents_service.workspace_search(search_request)

            return Response(
                {
                    "query": query,
                    "workspace_id": workspace_id,
                    "results": result.results,
                    "total": result.total,
                }
            )

        except Exception as e:
            return Response({"error": f"Search failed: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="image-chat")
    def image_chat(self, request):
        """Chat with images - placeholder."""
        return Response({"error": "Image chat is not implemented yet. Coming soon."}, status=501)


# ── Chain ViewSet ──
class ChainViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="conversation")
    def conversation(self, request):
        """Create a conversation chain with memory."""
        try:
            message = request.data.get("message", "")
            session_id = request.data.get("session_id", "default")

            if not message:
                return Response({"error": "Message is required"}, status=status.HTTP_400_BAD_REQUEST)

            use_mock = request.data.get("mock", False)
            if use_mock:
                return Response(
                    {
                        "message": message,
                        "response": f"Mock conversation chain response for session {session_id}: I received '{message}'",
                        "session_id": session_id,
                        "mock": True,
                    }
                )

            llm = agents_service.get_llm_port(
                provider=_resolve_llm_provider(request),
                model_name=request.data.get("model_name", "gpt-3.5-turbo"),
                temperature=0.7,
            )

            result = llm.chat(
                [
                    {"role": "system", "content": "You are a helpful AI assistant."},
                    {"role": "user", "content": message},
                ]
            )

            return Response(
                {
                    "message": message,
                    "response": result.content,
                    "session_id": session_id,
                }
            )

        except Exception as e:
            return Response({"error": f"Conversation chain error: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="qa")
    def qa(self, request):
        """Question-Answer chain for specific queries."""
        try:
            question = request.data.get("question", "")
            context = request.data.get("context", "")

            if not question:
                return Response({"error": "Question is required"}, status=status.HTTP_400_BAD_REQUEST)

            use_mock = request.data.get("mock", False)
            if use_mock:
                return Response(
                    {
                        "question": question,
                        "answer": f"Mock QA response: Based on the context, the answer to '{question}' is...",
                        "context_used": bool(context),
                        "mock": True,
                    }
                )

            llm = agents_service.get_llm_port(
                provider=_resolve_llm_provider(request),
                model_name=request.data.get("model_name", "gpt-3.5-turbo"),
                temperature=0.3,
            )

            prompt = f"Question: {question}\n"
            if context:
                prompt += f"Context: {context}\n"
            prompt += "Answer:"

            result = llm.invoke(prompt)

            return Response({"question": question, "answer": result.content, "context_used": bool(context)})

        except Exception as e:
            return Response({"error": f"QA chain error: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="retrieval")
    def retrieval(self, request):
        """Retrieval chain with document search."""
        try:
            question = request.data.get("question", "")
            conversation_id = request.data.get("conversation_id", "default")
            provider = request.data.get("provider", "elasticsearch")
            k = request.data.get("k", 4)

            if not question:
                return Response({"error": "Question is required"}, status=status.HTTP_400_BAD_REQUEST)

            stream_param = request.query_params.get("stream")
            stream_enabled = (
                str(stream_param).strip().lower() in {"1", "true", "yes", "y", "on"}
                if stream_param is not None
                else False
            )
            if stream_enabled:
                response = StreamingHttpResponse(
                    _stream_retrieval_events(
                        request=request,
                        question=question,
                        conversation_id=conversation_id,
                        provider=provider,
                        k=k,
                    ),
                    content_type="text/event-stream",
                )
                response["Cache-Control"] = "no-cache"
                response["X-Accel-Buffering"] = "no"
                return response

            use_mock = request.data.get("mock", False)
            if use_mock:
                return Response(
                    {
                        "question": question,
                        "answer": f"Mock retrieval response: Based on the documents, the answer to '{question}' is...",
                        "conversation_id": conversation_id,
                        "provider": provider,
                        "mock": True,
                    }
                )

            from components.agents.application.providers.retrieval_chain_provider import (
                get_retrieval_chain_provider,
            )

            _retrieval_provider = get_retrieval_chain_provider()

            llm = agents_service.get_llm_port(
                provider=_resolve_llm_provider(request),
                model_name=request.data.get("model_name", "gpt-3.5-turbo"),
                temperature=0.3,
            )

            retriever = agents_service.get_vector_store_port(
                provider=provider,
            ).search(query=question, k=k)

            retrieval_chain = _retrieval_provider.streaming_chain_from_llm(
                llm=llm,
                retriever=retriever,
                return_source_documents=True,
                metadata={"conversation_id": conversation_id},
            )

            response = retrieval_chain.get_retrieval_result(question)

            return Response(
                {
                    "question": question,
                    "answer": response["answer"],
                    "conversation_id": conversation_id,
                    "provider": provider,
                    "source_documents": [
                        {"content": doc.page_content, "metadata": doc.metadata}
                        for doc in response.get("source_documents", [])
                    ],
                }
            )

        except Exception as e:
            return Response({"error": f"Retrieval chain error: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="retrieval/stream")
    def retrieval_stream(self, request):
        """Retrieval chain with document search streamed via SSE."""
        question = request.data.get("question", "")
        conversation_id = request.data.get("conversation_id", "default")
        provider = request.data.get("provider", "elasticsearch")
        k = request.data.get("k", 4)

        if not question:
            return Response({"error": "Question is required"}, status=status.HTTP_400_BAD_REQUEST)

        def event_stream():
            yield from _stream_retrieval_events(
                request=request,
                question=question,
                conversation_id=conversation_id,
                provider=provider,
                k=k,
            )

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


# ── Memory ViewSet ──
class MemoryViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @_schema()
    @action(detail=False, methods=["get"], url_path="conversations")
    def list_conversations(self, request):
        """List all conversations for the user."""
        try:
            conversations = agents_service.list_conversations_for_user(request.user)

            workspace_id = request.query_params.get("workspace_id")
            pdf_id = request.query_params.get("pdf_id")
            if workspace_id:
                conversations = conversations.filter(metadata__workspace_id=workspace_id)
            if pdf_id:
                conversations = conversations.filter(metadata__pdf_id=pdf_id)

            from components.shared_kernel.application.providers.django_orm_provider import (
                get_django_orm_provider as _get_django_orm_provider,
            )

            _django_orm = _get_django_orm_provider()
            Count = _django_orm.Count

            conversations = conversations.order_by("-updated_at").annotate(message_count=Count("messages"))

            return Response(
                {
                    "conversations": [
                        {
                            "conversation_id": str(conv.id),
                            "title": conv.title,
                            "created_at": conv.created_at,
                            "updated_at": conv.updated_at,
                            "is_active": conv.is_active,
                            "message_count": getattr(conv, "message_count", conv.messages.count()),
                            "metadata": conv.metadata,
                        }
                        for conv in conversations
                    ]
                }
            )

        except Exception as e:
            return Response(
                {"error": f"Failed to list conversations: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema(request_body=True)
    @action(detail=False, methods=["post"], url_path="conversations/create")
    def create_conversation(self, request):
        """Create a new conversation."""
        try:
            user = request.user
            title = request.data.get("title", "New Conversation")
            workspace_id = request.data.get("workspace_id")
            pdf_id = request.data.get("pdf_id")

            metadata = {}
            if workspace_id:
                metadata["workspace_id"] = workspace_id
            if pdf_id:
                metadata["pdf_id"] = pdf_id

            conversation = agents_service.create_conversation(user=user, title=title, metadata=metadata)

            return Response(
                {
                    "conversation_id": str(conversation.id),
                    "title": conversation.title,
                    "created_at": conversation.created_at,
                    "user_id": str(conversation.user.id) if conversation.user else None,
                    "metadata": conversation.metadata,
                }
            )

        except Exception as e:
            return Response(
                {"error": f"Failed to create conversation: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema()
    # retrieve action
    def retrieve(self, request, pk=None):
        """Get conversation details and messages."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            Conversation = _pkg_models.Conversation
            conversation = get_object_or_404(Conversation, id=pk, user=request.user)
            messages = conversation.messages.all()

            return Response(
                {
                    "conversation_id": str(conversation.id),
                    "title": conversation.title,
                    "created_at": conversation.created_at,
                    "updated_at": conversation.updated_at,
                    "is_active": conversation.is_active,
                    "metadata": conversation.metadata,
                    "messages": [
                        {
                            "id": str(msg.id),
                            "role": msg.role,
                            "content": msg.content,
                            "created_at": msg.created_at,
                            "metadata": msg.metadata,
                        }
                        for msg in messages
                    ],
                }
            )

        except Http404:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"Failed to get conversation: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema(request_body=True)
    @action(detail=True, methods=["post"], url_path="messages")
    def add_message(self, request, pk=None):
        """Add a message to a conversation."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            Conversation = _pkg_models.Conversation
            conversation = get_object_or_404(Conversation, id=pk, user=request.user)
            role = request.data.get("role", "human")
            content = request.data.get("content", "")
            metadata = request.data.get("metadata", {})

            if not content:
                return Response({"error": "Content is required"}, status=status.HTTP_400_BAD_REQUEST)

            message = agents_service.create_message(
                conversation=conversation, role=role, content=content, metadata=metadata
            )

            return Response(
                {
                    "message_id": str(message.id),
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at,
                    "metadata": message.metadata,
                }
            )

        except Http404:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"Failed to add message: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @_schema()
    @action(detail=True, methods=["post"], url_path="clear")
    def clear_conversation(self, request, pk=None):
        """Clear all messages from a conversation."""
        try:
            from components.agents.application.providers.ai_models_provider import (
                get_ai_models_provider,
            )

            _pkg_models = get_ai_models_provider()
            Conversation = _pkg_models.Conversation
            conversation = get_object_or_404(Conversation, id=pk, user=request.user)
            agents_service.clear_conversation_messages(conversation.id, user=request.user)

            return Response({"message": "Conversation cleared successfully", "conversation_id": str(conversation.id)})

        except Http404:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"Failed to clear conversation: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ── Prompt Eval Reports ViewSet ──
#
# Wave 4 of the prompt-evaluation plan
# (``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``).
# Surfaces the JSON reports written by ``run_planner_eval`` so the
# V2 Command Center's HudPromptQualityPanel can read them without
# shelling onto a server.
#
# Reports live on the backend filesystem under
# ``docs/eval-reports/`` (the harness's default ``--output-dir``).
# They are gitignored — local to the box the eval was run on. In
# production the demo's docs/eval-reports/ is empty until someone
# runs the harness on the EC2 host; the panel renders an empty
# state until that happens.
class PromptEvalReportsViewSet(viewsets.GenericViewSet):
    """Read-only API surface for ``docs/eval-reports/*.json``."""

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _reports_dir() -> Path:
        import os
        from pathlib import Path

        configured = os.environ.get("PROMPT_EVAL_REPORTS_DIR")
        if configured:
            return Path(configured).expanduser().resolve()
        # ``__file__`` is .../components/agents/api/controller.py.
        # parents[3] is the repo root.
        return Path(__file__).resolve().parents[3] / "docs" / "eval-reports"

    def list(self, request):
        """Paginated list of reports, optionally filtered by prompt_id/version."""
        import json

        reports_dir = self._reports_dir()
        prompt_id_filter = request.query_params.get("prompt_id")
        version_filter = request.query_params.get("version")

        rows: list[dict] = []
        if reports_dir.exists():
            for path in sorted(reports_dir.glob("*.json"), reverse=True):
                try:
                    data = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "prompt_eval_report_unreadable path=%s err=%s",
                        path,
                        exc,
                    )
                    continue
                meta = data.get("_meta") or {}
                summary = {
                    "filename": path.name,
                    "prompt_id": meta.get("prompt_id") or data.get("prompt_id") or "planner.system",
                    "version": meta.get("version") or data.get("version") or "",
                    "label": meta.get("label") or data.get("label") or "",
                    "created_at": meta.get("created_at") or data.get("created_at") or "",
                    "case_count": int(data.get("case_count") or len(data.get("cases") or [])),
                    "avg_score": float(data.get("average_score") or 0.0),
                    "pass_rate_at_seven": float(data.get("pass_rate_at_seven") or 0.0),
                    "score_by_category": data.get("score_by_category") or {},
                }
                if prompt_id_filter and summary["prompt_id"] != prompt_id_filter:
                    continue
                if version_filter and summary["version"] != version_filter:
                    continue
                rows.append(summary)

        paginator = self.paginator
        page = paginator.paginate_queryset(rows, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(page)
        return Response(rows)

    def retrieve(self, request, pk=None, **kwargs):
        """Return the full report JSON for one filename.

        DRF's default router treats trailing ``.json`` as a format
        suffix, so a request to ``/ai/prompt-eval/reports/foo.json/``
        arrives here as ``pk='foo', format='json'``. Reconstruct the
        actual filename from the pk + format kwarg before validating.
        """
        import json

        fmt = kwargs.get("format") or ""
        filename = f"{pk}.{fmt}" if fmt else (pk or "")
        if not filename or "/" in filename or filename.startswith(".") or not filename.endswith(".json"):
            return Response(
                {"error": "filename must be a *.json report stem (no slashes / dots)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        path = self._reports_dir() / filename
        try:
            path = path.resolve(strict=True)
        except FileNotFoundError:
            return Response(
                {"error": f"report not found: {filename}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not str(path).startswith(str(self._reports_dir().resolve())):
            # Defence in depth against path traversal — the validation
            # above already rejects any pk with a slash, but the resolved
            # path check ensures a symlink can't escape the dir either.
            return Response(
                {"error": "report path outside the reports directory."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            return Response(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            return Response(
                {"error": f"report unreadable: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ── Health ViewSet ──
class HealthViewSet(viewsets.GenericViewSet):
    @_schema()
    @action(detail=False, methods=["get"], url_path="health")
    def health_check(self, request):
        """AI module health check and overview."""
        return Response(
            {
                "status": "healthy",
                "module": "ai",
                "version": "2.0",
                "endpoints": {
                    "health": "/ai/health/",
                    "conversations": {
                        "list": "/ai/conversations/",
                        "create": "/ai/conversations/create/",
                        "messages": "/ai/conversations/<id>/messages/create/",
                    },
                    "llms": {
                        "openai": "/ai/llms/openai/",
                        "langchain": "/ai/llms/langchain/",
                        "models": "/ai/llms/models/",
                        "providers": "/ai/llms/providers/",
                    },
                    "chains": {
                        "conversation": "/ai/chains/conversation/",
                        "qa": "/ai/chains/qa/",
                        "retrieval": "/ai/chains/retrieval/",
                        "retrieval_stream": "/ai/chains/retrieval/stream/",
                    },
                    "embeddings": {
                        "create": "/ai/embeddings/create/",
                        "batch": "/ai/embeddings/batch/",
                        "similarity": "/ai/embeddings/similarity/",
                        "providers": "/ai/embeddings/providers/",
                    },
                    "memories": {
                        "conversations": "/ai/memories/conversations/",
                        "messages": "/ai/memories/conversations/<id>/messages/",
                    },
                    "vector_stores": {
                        "documents": "/ai/vector_stores/documents/",
                        "search": "/ai/vector_stores/search/",
                        "providers": "/ai/vector_stores/providers/",
                    },
                    "callbacks": "/ai/callbacks/",
                    "tracing": "/ai/tracing/",
                },
                "configuration": {
                    "openai_configured": bool(os.environ.get("OPENAI_API_KEY")),
                    "elasticsearch_configured": _is_elasticsearch_configured(),
                    "langchain_available": True,
                    "mock_mode_available": True,
                },
            }
        )

    @_schema()
    @action(detail=False, methods=["get"], url_path="status")
    def module_status(self, request):
        """Get status of all AI modules."""
        return Response(
            {
                "modules": {
                    "llms": {"status": "active", "endpoints": 4},
                    "chains": {"status": "active", "endpoints": 4},
                    "embeddings": {"status": "active", "endpoints": 4},
                    "memories": {"status": "active", "endpoints": 5},
                    "vector_stores": {"status": "active", "endpoints": 5},
                    "callbacks": {"status": "active", "endpoints": 1},
                    "tracing": {"status": "active", "endpoints": 1},
                },
                "total_endpoints": 24,
                "active_modules": 7,
            }
        )

    @_schema()
    @action(detail=False, methods=["get"], url_path="test")
    def test_endpoints(self, request):
        """Test all AI endpoints functionality."""

        base_url = request.build_absolute_uri("/")
        test_results = {}

        endpoints_to_test = [
            {"name": "LLM Providers", "method": "GET", "url": f"{base_url}ai/llms/providers/", "data": None},
            {"name": "LLM Models", "method": "GET", "url": f"{base_url}ai/llms/models/", "data": None},
            {
                "name": "OpenAI Chat (Mock)",
                "method": "POST",
                "url": f"{base_url}ai/llms/openai/",
                "data": {"message": "Hello AI!", "mock": True},
            },
            {
                "name": "Embeddings Providers",
                "method": "GET",
                "url": f"{base_url}ai/embeddings/providers/",
                "data": None,
            },
            {
                "name": "Create Embedding (Mock)",
                "method": "POST",
                "url": f"{base_url}ai/embeddings/create/",
                "data": {"text": "Test document", "mock": True},
            },
            {
                "name": "Vector Store Providers",
                "method": "GET",
                "url": f"{base_url}ai/vector_stores/providers/",
                "data": None,
            },
            {
                "name": "Conversation Chain (Mock)",
                "method": "POST",
                "url": f"{base_url}ai/chains/conversation/",
                "data": {"message": "Hello!", "session_id": "test", "mock": True},
            },
        ]

        for endpoint in endpoints_to_test:
            try:
                if endpoint["method"] == "GET":
                    response = requests.get(endpoint["url"], timeout=5)
                else:
                    response = requests.post(endpoint["url"], json=endpoint["data"], timeout=5)

                test_results[endpoint["name"]] = {
                    "status": "success" if response.status_code == 200 else "failed",
                    "status_code": response.status_code,
                    "response_time": response.elapsed.total_seconds(),
                }
            except Exception as e:
                test_results[endpoint["name"]] = {"status": "error", "error": str(e), "response_time": 0}

        total_tests = len(test_results)
        successful_tests = sum(1 for result in test_results.values() if result["status"] == "success")

        return Response(
            {
                "test_summary": {
                    "total_tests": total_tests,
                    "successful_tests": successful_tests,
                    "failed_tests": total_tests - successful_tests,
                    "success_rate": f"{(successful_tests / total_tests * 100):.1f}%",
                },
                "test_results": test_results,
                "base_url": base_url,
            }
        )
