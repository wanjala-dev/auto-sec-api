"""ORM adapter for agent engagement read queries.

Extracted from agents_controller.py list_agent_ratings, list_agent_comments,
get_shared_agent.
"""
from __future__ import annotations

from typing import Any

from components.agents.domain.errors import (
    AgentDisabledError,
    AgentNotFoundError,
    AgentPermissionError,
    ShareNotFoundError,
)
from components.agents.application.ports.agent_engagement_query_port import (
    AgentEngagementQueryPort,
    GetSharedAgentRequest,
    ListCommentsData,
    ListCommentsRequest,
    ListRatingsData,
    ListRatingsRequest,
    SharedAgentData,
)


class OrmAgentEngagementQueryRepository(AgentEngagementQueryPort):

    @staticmethod
    def _get_agent(agent_id: str):
        from infrastructure.persistence.ai.agents.models import Agent
        try:
            return Agent.objects.select_related("profile", "workspace").get(agent_id=agent_id)
        except Agent.DoesNotExist:
            raise AgentNotFoundError("Agent not found")

    @staticmethod
    def _check_access(user, agent, *, include_followers: bool = False) -> None:
        if not user or not agent:
            raise AgentPermissionError("Permission denied")
        if str(agent.user_id) == str(getattr(user, "id", None)):
            return
        workspace = agent.workspace
        if not workspace:
            raise AgentPermissionError("Permission denied")
        from components.workspace.application.facades.workspace_facade import user_is_workspace_member
        if user_is_workspace_member(user, workspace):
            return
        if include_followers:
            from infrastructure.persistence.ai.agents.models import AgentFollow
            if AgentFollow.objects.filter(agent=agent, user=user).exists():
                return
        raise AgentPermissionError("Permission denied")

    def list_ratings(self, *, request: ListRatingsRequest, http_request: Any = None) -> ListRatingsData:
        from rest_framework.pagination import PageNumberPagination
        from infrastructure.persistence.ai.agents.models import AgentRating
        from components.agents.mappers.rest.agents_serializers import RatingSerializer

        agent = self._get_agent(request.agent_id)
        profile = getattr(agent, "profile", None)
        if profile and profile.is_disabled:
            raise AgentDisabledError("Agent is disabled")
        self._check_access(request.user, agent, include_followers=True)

        ratings = AgentRating.objects.filter(agent=agent).select_related("user").order_by("-created_at")

        class _Paginator(PageNumberPagination):
            page_size = request.page_size
            page_size_query_param = "page_size"
            max_page_size = 100

        paginator = _Paginator()
        page = paginator.paginate_queryset(ratings, http_request)
        serializer = RatingSerializer(page, many=True)

        paginated = paginator.get_paginated_response(serializer.data)
        return ListRatingsData(
            ratings=paginated.data.get("results", []),
            count=paginated.data.get("count", 0),
            next_url=paginated.data.get("next"),
            previous_url=paginated.data.get("previous"),
        )

    def list_comments(self, *, request: ListCommentsRequest, http_request: Any = None) -> ListCommentsData:
        from rest_framework.pagination import PageNumberPagination
        from infrastructure.persistence.ai.agents.models import AgentComment
        from components.agents.mappers.rest.agents_serializers import CommentSerializer

        agent = self._get_agent(request.agent_id)
        profile = getattr(agent, "profile", None)
        if profile and profile.is_disabled:
            raise AgentDisabledError("Agent is disabled")
        self._check_access(request.user, agent, include_followers=True)

        qs = (
            AgentComment.objects.filter(agent=agent, parent__isnull=True)
            .select_related("user")
            .order_by("-created_at")
        )

        class _Paginator(PageNumberPagination):
            page_size = request.page_size
            page_size_query_param = "page_size"
            max_page_size = 100

        paginator = _Paginator()
        page = paginator.paginate_queryset(qs, http_request)

        data = []
        for comment in page:
            item = CommentSerializer(comment).data
            replies = comment.replies.select_related("user").all()[:20]
            item["replies"] = CommentSerializer(replies, many=True).data
            data.append(item)

        paginated = paginator.get_paginated_response(data)
        return ListCommentsData(
            comments=paginated.data.get("results", []),
            count=paginated.data.get("count", 0),
            next_url=paginated.data.get("next"),
            previous_url=paginated.data.get("previous"),
        )

    def get_shared_agent(self, *, request: GetSharedAgentRequest) -> SharedAgentData:
        from django.db.models import Avg, Count, Q
        from infrastructure.persistence.ai.agents.models import Agent, AgentProfile, AgentShare
        from components.agents.mappers.rest.agents_serializers import AgentProfileSerializer

        share = (
            AgentShare.objects.select_related("agent", "agent__profile", "agent__workspace")
            .filter(share_token=request.share_token)
            .first()
        )
        if not share or not share.is_active():
            raise ShareNotFoundError("Not found")

        agent = share.agent
        profile, _ = AgentProfile.objects.get_or_create(agent=agent)
        if profile and profile.is_disabled:
            raise ShareNotFoundError("Not found")

        # Scope check: workspace_only requires auth + membership
        if share.scope == AgentShare.SCOPE_WORKSPACE_ONLY:
            if not request.user or not getattr(request.user, "is_authenticated", False):
                raise AgentPermissionError("Authentication required")
            self._check_access(
                request.user, agent,
                include_followers=bool(profile and profile.allow_followers),
            )

        # Build engagement counts
        annotated = (
            Agent.objects.annotate(
                followers_count=Count("follows", distinct=True),
                likes_count=Count("reactions", filter=Q(reactions__reaction_type="like"), distinct=True),
                rating_avg=Avg("ratings__score"),
                rating_count=Count("ratings", distinct=True),
                comment_count=Count("comments", distinct=True),
            )
            .get(agent_id=agent.agent_id)
        )
        counts = {
            "likes": getattr(annotated, "likes_count", 0) or 0,
            "followers": getattr(annotated, "followers_count", 0) or 0,
            "rating_avg": float(getattr(annotated, "rating_avg", 0) or 0),
            "rating_count": getattr(annotated, "rating_count", 0) or 0,
            "comment_count": getattr(annotated, "comment_count", 0) or 0,
        }

        profile_data = AgentProfileSerializer(profile).data if profile else {}
        return SharedAgentData(
            agent_id=str(agent.agent_id),
            profile=profile_data,
            engagement_counts=counts,
            is_disabled=bool(profile and profile.is_disabled),
        )
