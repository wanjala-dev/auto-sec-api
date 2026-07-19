"""ORM adapter for agent engagement write operations.

Extracted from agents_controller.py engagement cluster
(follow/unfollow/like/unlike/rate/comment/share/revoke).
"""
from __future__ import annotations

from typing import Any

from components.agents.domain.errors import (
    AgentDisabledError,
    AgentEngagementError,
    AgentNotFoundError,
    AgentPermissionError,
    InvalidCommentError,
    InvalidShareScopeError,
    ShareNotFoundError,
)
from components.agents.application.ports.agent_engagement_port import (
    AgentEngagementPort,
    CommentRequest,
    CommentResult,
    EngagementCounts,
    FollowRequest,
    FollowResult,
    LikeRequest,
    LikeResult,
    RateRequest,
    RateResult,
    RevokeShareRequest,
    RevokeShareResult,
    ShareRequest,
    ShareResult,
)


class OrmAgentEngagementRepository(AgentEngagementPort):

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _get_agent(agent_id: str):
        from infrastructure.persistence.ai.agents.models import Agent
        try:
            return Agent.objects.select_related("profile", "workspace").get(agent_id=agent_id)
        except Agent.DoesNotExist:
            raise AgentNotFoundError("Agent not found")

    @staticmethod
    def _get_or_create_profile(agent):
        from infrastructure.persistence.ai.agents.models import AgentProfile
        profile, _ = AgentProfile.objects.get_or_create(agent=agent)
        return profile

    @staticmethod
    def _check_profile_enabled(profile) -> None:
        if profile and profile.is_disabled:
            raise AgentDisabledError("Agent is disabled")

    @staticmethod
    def _check_access(user, agent, *, include_followers: bool = False) -> None:
        """Check workspace-level access to agent."""
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

    @staticmethod
    def _check_ai_permission(http_request, agent, perm: str) -> None:
        """Check AI-specific permission (ai_engage, ai_manage)."""
        from components.agents.application.facades.agent_permissions_facade import AgentAIPermission
        checker = AgentAIPermission()

        class _View:
            required_ai_perm = perm

        view = _View()
        if not checker.has_permission(http_request, view):
            raise AgentPermissionError("Permission denied")
        if not checker.has_object_permission(http_request, view, agent):
            raise AgentPermissionError("Permission denied")

    @staticmethod
    def _refresh_engagement_counts(agent_id: str) -> EngagementCounts:
        from django.db.models import Avg, Count, Q
        from infrastructure.persistence.ai.agents.models import Agent

        agent = (
            Agent.objects.select_related("profile", "workspace")
            .annotate(
                followers_count=Count("follows", distinct=True),
                likes_count=Count("reactions", filter=Q(reactions__reaction_type="like"), distinct=True),
                rating_avg=Avg("ratings__score"),
                rating_count=Count("ratings", distinct=True),
                comment_count=Count("comments", distinct=True),
            )
            .get(agent_id=agent_id)
        )
        return EngagementCounts(
            likes=getattr(agent, "likes_count", 0) or 0,
            followers=getattr(agent, "followers_count", 0) or 0,
            rating_avg=float(getattr(agent, "rating_avg", 0) or 0),
            rating_count=getattr(agent, "rating_count", 0) or 0,
            comment_count=getattr(agent, "comment_count", 0) or 0,
        )

    # ── write operations ─────────────────────────────────────────────

    def follow_agent(self, *, request: FollowRequest) -> FollowResult:
        from django.db import transaction
        from infrastructure.persistence.ai.agents.models import AgentFollow

        agent = self._get_agent(request.agent_id)
        profile = self._get_or_create_profile(agent)
        self._check_profile_enabled(profile)
        self._check_access(request.user, agent, include_followers=bool(profile and profile.allow_followers))

        with transaction.atomic():
            AgentFollow.objects.get_or_create(agent=agent, user=request.user)

        counts = self._refresh_engagement_counts(request.agent_id)
        return FollowResult(following=True, engagement_counts=counts)

    def unfollow_agent(self, *, request: FollowRequest) -> FollowResult:
        from infrastructure.persistence.ai.agents.models import AgentFollow

        agent = self._get_agent(request.agent_id)
        AgentFollow.objects.filter(agent=agent, user=request.user).delete()

        counts = self._refresh_engagement_counts(request.agent_id)
        return FollowResult(following=False, engagement_counts=counts)

    def like_agent(self, *, request: LikeRequest, http_request: Any = None) -> LikeResult:
        from django.db import transaction
        from infrastructure.persistence.ai.agents.models import AgentReaction

        agent = self._get_agent(request.agent_id)
        profile = self._get_or_create_profile(agent)
        self._check_profile_enabled(profile)
        if http_request:
            self._check_ai_permission(http_request, agent, "ai_engage")

        with transaction.atomic():
            AgentReaction.objects.update_or_create(
                agent=agent, user=request.user, reaction_type="like",
            )

        counts = self._refresh_engagement_counts(request.agent_id)
        return LikeResult(liked=True, engagement_counts=counts)

    def unlike_agent(self, *, request: LikeRequest) -> LikeResult:
        from infrastructure.persistence.ai.agents.models import AgentReaction

        agent = self._get_agent(request.agent_id)
        AgentReaction.objects.filter(agent=agent, user=request.user, reaction_type="like").delete()

        counts = self._refresh_engagement_counts(request.agent_id)
        return LikeResult(liked=False, engagement_counts=counts)

    def rate_agent(self, *, request: RateRequest, http_request: Any = None) -> RateResult:
        from django.db import transaction
        from infrastructure.persistence.ai.agents.models import AgentRating
        from components.agents.mappers.rest.agents_serializers import RatingSerializer

        agent = self._get_agent(request.agent_id)
        profile = self._get_or_create_profile(agent)
        self._check_profile_enabled(profile)
        if profile and not profile.allow_ratings:
            raise AgentEngagementError("Ratings disabled for this agent")
        if http_request:
            self._check_ai_permission(http_request, agent, "ai_engage")

        payload = {"agent": agent.id, "user": request.user.id, "score": request.score, "comment": request.comment}
        serializer = RatingSerializer(data=payload)
        if not serializer.is_valid():
            raise AgentEngagementError(str(serializer.errors))

        with transaction.atomic():
            AgentRating.objects.update_or_create(
                agent=agent,
                user=request.user,
                defaults={
                    "score": serializer.validated_data["score"],
                    "comment": serializer.validated_data.get("comment", ""),
                },
            )

        counts = self._refresh_engagement_counts(request.agent_id)
        return RateResult(rated=True, engagement_counts=counts)

    def comment_agent(self, *, request: CommentRequest, http_request: Any = None) -> CommentResult:
        from infrastructure.persistence.ai.agents.models import AgentComment
        from components.agents.mappers.rest.agents_serializers import CommentSerializer

        agent = self._get_agent(request.agent_id)
        profile = self._get_or_create_profile(agent)
        self._check_profile_enabled(profile)
        if profile and not profile.allow_comments:
            raise AgentEngagementError("Comments disabled for this agent")
        if http_request:
            self._check_ai_permission(http_request, agent, "ai_engage")

        payload = {
            "agent": agent.id,
            "user": request.user.id,
            "body": request.body,
            "parent": request.parent_id,
        }
        serializer = CommentSerializer(data=payload)
        if not serializer.is_valid():
            raise InvalidCommentError(str(serializer.errors))

        parent = serializer.validated_data.get("parent")
        if parent and parent.agent_id != agent.id:
            raise InvalidCommentError("Invalid parent")
        if parent and parent.parent_id:
            raise InvalidCommentError("Maximum comment depth exceeded")

        AgentComment.objects.create(
            agent=agent,
            user=request.user,
            body=serializer.validated_data["body"],
            parent=parent,
        )

        counts = self._refresh_engagement_counts(request.agent_id)
        return CommentResult(commented=True, engagement_counts=counts)

    def share_agent(self, *, request: ShareRequest, http_request: Any = None) -> ShareResult:
        from infrastructure.persistence.ai.agents.models import AgentShare
        from components.agents.mappers.rest.agents_serializers import ShareSerializer

        agent = self._get_agent(request.agent_id)
        if http_request:
            self._check_ai_permission(http_request, agent, "ai_manage")

        scope = request.scope or AgentShare.SCOPE_SEED_ONLY
        if scope not in dict(AgentShare.SCOPE_CHOICES):
            raise InvalidShareScopeError("Invalid scope")

        serializer = ShareSerializer(data={"scope": scope, "expires_at": request.expires_at})
        if not serializer.is_valid():
            raise InvalidShareScopeError(str(serializer.errors))

        token = ShareSerializer.generate_token()
        share = serializer.save(agent=agent, share_token=token)
        response = ShareSerializer(share)
        return ShareResult(
            share_data=response.data,
            share_url=f"/ai/agents/shared/{token}/",
        )

    def revoke_share(self, *, request: RevokeShareRequest, http_request: Any = None) -> RevokeShareResult:
        from infrastructure.persistence.ai.agents.models import AgentShare

        share = (
            AgentShare.objects.select_related("agent", "agent__profile", "agent__workspace")
            .filter(share_token=request.share_token)
            .first()
        )
        if not share:
            raise ShareNotFoundError("Not found")
        if http_request:
            self._check_ai_permission(http_request, share.agent, "ai_manage")
        share.delete()
        return RevokeShareResult(revoked=True)
