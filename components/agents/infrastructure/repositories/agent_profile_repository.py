"""ORM adapter for agent profile / state operations.

Extracted from agents_controller.py get_agent_state, get_agent_profile,
patch_agent_profile, patch_agent_settings.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.agent_profile_port import (
    AgentProfileData,
    AgentProfilePort,
    AgentStateData,
    GetAgentProfileRequest,
    GetAgentStateRequest,
    PatchAgentProfileCommand,
    PatchAgentProfileResult,
    PatchAgentSettingsCommand,
    PatchAgentSettingsResult,
)
from components.agents.domain.errors import (
    AgentEngagementError,
    AgentNotFoundError,
    AgentPermissionError,
)


class OrmAgentProfileRepository(AgentProfilePort):
    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _get_agent_with_engagement(agent_id: str):
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
            .filter(agent_id=agent_id)
            .first()
        )
        if not agent:
            raise AgentNotFoundError("Agent not found")
        return agent

    @staticmethod
    def _build_engagement_counts(agent) -> dict[str, Any]:
        return {
            "likes": getattr(agent, "likes_count", 0) or 0,
            "followers": getattr(agent, "followers_count", 0) or 0,
            "rating_avg": float(getattr(agent, "rating_avg", 0) or 0),
            "rating_count": getattr(agent, "rating_count", 0) or 0,
            "comment_count": getattr(agent, "comment_count", 0) or 0,
        }

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

    @staticmethod
    def _check_ai_permission(http_request, agent, perm: str) -> None:
        from components.agents.application.facades.agent_permissions_facade import AgentAIPermission

        checker = AgentAIPermission()

        class _View:
            required_ai_perm = perm

        view = _View()
        if not checker.has_permission(http_request, view):
            raise AgentPermissionError("Permission denied")
        if not checker.has_object_permission(http_request, view, agent):
            raise AgentPermissionError("Permission denied")

    # ── port methods ─────────────────────────────────────────────────

    def get_agent_state(self, *, request: GetAgentStateRequest) -> AgentStateData:
        from components.agents.infrastructure.services.agents_service import get_agent_service
        from components.agents.mappers.rest.agents_serializers import AgentProfileSerializer
        from infrastructure.persistence.ai.agents.models import AgentProfile

        agent_record = self._get_agent_with_engagement(request.agent_id)

        if str(agent_record.user_id) != request.user_id:
            raise AgentPermissionError("Permission denied")

        factory = get_agent_service()
        agent = factory.get_agent(request.agent_id)
        if not agent:
            raise AgentNotFoundError("Agent not found")

        profile, _ = AgentProfile.objects.get_or_create(agent=agent_record)
        profile_data = AgentProfileSerializer(profile).data if profile else None
        counts = self._build_engagement_counts(agent_record)

        return AgentStateData(
            agent_id=request.agent_id,
            state=agent.get_state(),
            profile=profile_data,
            engagement_counts=counts,
            is_disabled=bool(profile and profile.is_disabled),
        )

    def get_agent_profile(self, *, request: GetAgentProfileRequest) -> AgentProfileData:
        from components.agents.mappers.rest.agents_serializers import (
            AgentEngagementCountsSerializer,
            AgentProfileSerializer,
        )
        from infrastructure.persistence.ai.agents.models import AgentProfile

        agent = self._get_agent_with_engagement(request.agent_id)
        profile, _ = AgentProfile.objects.get_or_create(agent=agent)
        self._check_access(
            request.user,
            agent,
            include_followers=bool(profile and profile.allow_followers),
        )

        serializer = AgentProfileSerializer(profile or AgentProfile(agent=agent))
        counts = AgentEngagementCountsSerializer(self._build_engagement_counts(agent)).data

        return AgentProfileData(
            agent_id=str(agent.agent_id),
            profile=serializer.data,
            engagement_counts=counts,
            is_disabled=bool(profile and profile.is_disabled),
        )

    def patch_agent_profile(self, *, command: PatchAgentProfileCommand) -> PatchAgentProfileResult:
        from components.agents.mappers.rest.agents_serializers import (
            AgentEngagementCountsSerializer,
            AgentProfileSerializer,
        )
        from infrastructure.persistence.ai.agents.models import AgentProfile

        agent = self._get_agent_with_engagement(command.agent_id)
        profile, _ = AgentProfile.objects.get_or_create(agent=agent)

        if command.http_request:
            self._check_ai_permission(command.http_request, agent, "ai_manage")

        serializer = AgentProfileSerializer(profile, data=command.data, partial=True)
        if not serializer.is_valid():
            raise AgentEngagementError(str(serializer.errors))

        serializer.save()
        counts = AgentEngagementCountsSerializer(self._build_engagement_counts(agent)).data

        return PatchAgentProfileResult(
            agent_id=str(agent.agent_id),
            profile=serializer.data,
            engagement_counts=counts,
            is_disabled=serializer.data.get("is_disabled", False),
        )

    def patch_agent_settings(self, *, command: PatchAgentSettingsCommand) -> PatchAgentSettingsResult:
        from components.agents.mappers.rest.agents_serializers import AgentProfileSerializer
        from infrastructure.persistence.ai.agents.models import Agent, AgentProfile

        agent = self._get_agent_with_engagement(command.agent_id)
        profile, _ = AgentProfile.objects.get_or_create(agent=agent)

        if command.http_request:
            self._check_ai_permission(command.http_request, agent, "ai_manage")

        # Update custom settings
        custom_profile = (agent.config or {}).get("custom_profile", {}) if isinstance(agent.config, dict) else {}
        allowed_keys = {"persona", "tone", "tool_whitelist", "output_format", "default_report_period"}
        sanitized_updates = {k: v for k, v in (command.data or {}).items() if k in allowed_keys}

        if sanitized_updates:
            merged_config = dict(agent.config or {})
            merged_custom = dict(custom_profile or {})
            merged_custom.update(sanitized_updates)
            merged_config["custom_profile"] = merged_custom
            Agent.objects.filter(agent_id=agent.agent_id).update(config=merged_config)

            try:
                from components.agents.infrastructure.services.agents_service import get_agent_service

                service = get_agent_service()
                instance = service.get_agent(str(agent.agent_id))
                if instance:
                    instance.config["custom_profile"] = merged_custom
            except Exception:
                pass

        serializer = AgentProfileSerializer(profile, data=command.data, partial=True)
        if not serializer.is_valid():
            raise AgentEngagementError(str(serializer.errors))

        serializer.save()
        if serializer.validated_data.get("is_disabled"):
            Agent.objects.filter(agent_id=agent.agent_id).update(status="paused")

        return PatchAgentSettingsResult(profile=serializer.data)

    # Capabilities toggleable via the API. Adding a new gated capability means
    # adding it here AND wiring the tool/use case that reads it — never accept
    # arbitrary keys (capabilities unlock risk-gated tools; this allowlist is
    # the API-side half of that gate).
    ALLOWED_CAPABILITIES = {"open_draft_pr"}

    def patch_agent_capabilities(self, *, command):
        """Merge boolean toggles into ``Agent.config.capabilities``.

        Same permission gate as settings (``ai_manage``), but a separate,
        stricter surface: only allowlisted capability keys, values coerced to
        bool, and the merged map returned so the UI can render current state.
        """
        from components.agents.application.ports.agent_profile_port import PatchAgentCapabilitiesResult
        from infrastructure.persistence.ai.agents.models import Agent

        agent = self._get_agent_with_engagement(command.agent_id)

        if command.http_request:
            self._check_ai_permission(command.http_request, agent, "ai_manage")

        unknown = set((command.data or {}).keys()) - self.ALLOWED_CAPABILITIES
        if unknown:
            raise AgentEngagementError(f"Unknown capabilities: {', '.join(sorted(unknown))}")
        updates = {key: bool(value) for key, value in (command.data or {}).items()}

        merged_config = dict(agent.config or {})
        capabilities = dict(merged_config.get("capabilities") or {})
        capabilities.update(updates)
        merged_config["capabilities"] = capabilities
        Agent.objects.filter(agent_id=agent.agent_id).update(config=merged_config)

        return PatchAgentCapabilitiesResult(capabilities=capabilities)
