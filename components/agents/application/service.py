"""Application service for the agents bounded context.

Orchestration only – delegates to use cases via the Command Bus
(CQRS write side) or directly via AIProvider for use cases not
yet registered with the bus.

Graca's Explicit Architecture: *"The controller constructs a Command
and passes it to the relevant Bus."*
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from components.agents.application.providers.ai_provider import AIProvider
from components.shared_kernel.application.commands import Command
from components.shared_kernel.application.ports.command_bus import CommandBus


@dataclass
class AgentsService:
    """Application service for the agents bounded context.

    Orchestration only – routes commands through the bus or delegates
    to use cases for non-bus operations.
    """

    provider: AIProvider = field(default_factory=AIProvider)
    _command_bus: CommandBus | None = field(default=None, init=False, repr=False)

    @property
    def command_bus(self) -> CommandBus:
        if self._command_bus is None:
            self._command_bus = self.provider.build_command_bus()
        return self._command_bus

    def dispatch(self, command: Command) -> Any:
        """Dispatch any registered command through the bus."""
        return self.command_bus.dispatch(command)

    # ── Metered AI quota (Free/Pro/Premium) ──────────────────────────
    #
    # ``execute`` + ``deep_run`` count against MAX_AI_RUNS_PER_MONTH; chat
    # does NOT (it goes through ``agent_chat`` → the chat use case's own deep
    # port, never these methods, so it never checks or records). The flow is
    # check-then-run-then-record so a rejected run never consumes allowance
    # and a failed run isn't tallied.

    @staticmethod
    def _raise_if_over(status) -> None:
        """Raise ``AiRunLimitExceeded`` when the monthly allowance is spent."""
        if status.allowed:
            return
        from components.agents.domain.errors import AiRunLimitExceeded

        raise AiRunLimitExceeded(
            used=status.used,
            limit=status.limit,
            workspace_id=status.workspace_id,
        )

    @staticmethod
    def _raise_if_ai_killed(workspace_id) -> None:
        """Raise ``AiUnavailable`` when AI is halted for this workspace.

        Two independent stops compose here:

        1. The emergency operator flag (``feature.ai_kill_switch``).
        2. The workspace kill switch (``Workspace.ai_teammate_enabled``) —
           the same value the chat gate, the entitlement gate and the
           detector fan-out read. Before the governance slice the deep-run
           entry points (``deep_run_plan`` / ``deep_plan_and_run`` /
           ``execute_agent``) only checked the flag, so a paused workspace
           still burned planner/synthesizer LLM calls even though every
           specialist dispatch inside the run was entitlement-blocked. The
           run now refuses at the door.

        ``workspace_id`` falsy → skip (workspace-less runs have no
        workspace switch to consult; the emergency flag also no-ops).
        """
        from components.agents.application.policies.agent_entitlements import (
            workspace_ai_paused,
        )
        from components.agents.application.policies.ai_kill_switch import is_ai_killed

        if is_ai_killed(workspace_id):
            from components.agents.domain.errors import AiUnavailable

            raise AiUnavailable(workspace_id=str(workspace_id) if workspace_id else None)
        if workspace_id and workspace_ai_paused(str(workspace_id)):
            from components.agents.domain.errors import AiUnavailable

            raise AiUnavailable(
                workspace_id=str(workspace_id),
                message=(
                    "AI is paused for this workspace. A workspace admin can resume it from the kill-switch control."
                ),
            )

    # ── Commands dispatched through the bus ──────────────────────────

    def create_agent(self, command) -> Any:
        """Create an agent."""
        return self.command_bus.dispatch(command)

    def delete_agent(self, command) -> Any:
        """Delete an agent."""
        return self.command_bus.dispatch(command)

    def dispatch_agent_state(self, command) -> Any:
        """Dispatch agent state command (pause/resume) through the bus."""
        return self.command_bus.dispatch(command)

    def agent_chat(self, command) -> Any:
        """Unified chat — every message runs through the deep-agent pipeline.

        Bypasses the command bus (and its ``transaction_middleware``) on
        purpose: the deep run makes 10-30s of external LLM calls inside
        its body, and wrapping the whole thing in a single
        ``transaction.atomic()`` holds a DB connection + transaction open
        for that entire window.  That was observed hanging the HTTP
        request under local load (concurrent `/imports/` polling).  Each
        ORM write inside the deep run (DeepRun upserts, etc.) is
        individually atomic by Django's default autocommit, which is the
        right granularity here.
        """
        use_case = self.provider.build_agent_chat_use_case()
        return use_case.execute(command)

    def pdf_chat(self, command) -> Any:
        """Chat with PDF context."""
        return self.command_bus.dispatch(command)

    def pdf_summary(self, command) -> Any:
        """Generate PDF summary."""
        return self.command_bus.dispatch(command)

    def deep_run_plan(self, command, **kwargs) -> Any:
        """Plan a deep run (metered)."""
        self._raise_if_ai_killed(getattr(command, "workspace_id", None))
        quota = self.provider.build_ai_run_quota()
        status = quota.check_for_workspace(getattr(command, "workspace_id", None))
        self._raise_if_over(status)
        result = self.command_bus.dispatch(command)
        quota.record_run(status.workspace_id)
        return result

    def deep_plan_and_run(self, command) -> Any:
        """Plan and execute a deep run (metered)."""
        self._raise_if_ai_killed(getattr(command, "workspace_id", None))
        quota = self.provider.build_ai_run_quota()
        status = quota.check_for_workspace(getattr(command, "workspace_id", None))
        self._raise_if_over(status)
        result = self.command_bus.dispatch(command)
        quota.record_run(status.workspace_id)
        return result

    # ── Commands still dispatched directly (not yet on bus) ──────────

    def execute_agent(self, command) -> Any:
        """Execute an agent (metered)."""
        self._raise_if_ai_killed(getattr(command, "workspace_id", None))
        quota = self.provider.build_ai_run_quota()
        status = quota.check_for_agent(getattr(command, "agent_id", None))
        self._raise_if_over(status)
        use_case = self.provider.build_execute_agent_use_case()
        result = use_case.execute(command)
        quota.record_run(status.workspace_id)
        return result

    def set_agent_entitlement(self, command) -> Any:
        """Set agent entitlement."""
        use_case = self.provider.build_set_entitlement_use_case()
        return use_case.execute(command)

    def patch_agent_profile(self, command) -> Any:
        """Patch agent profile."""
        use_case = self.provider.build_patch_agent_profile_use_case()
        return use_case.execute(command)

    def patch_agent_settings(self, command) -> Any:
        """Patch agent settings."""
        use_case = self.provider.build_patch_agent_settings_use_case()
        return use_case.execute(command)

    def patch_agent_capabilities(self, command) -> Any:
        """Toggle allowlisted, risk-gating agent capabilities."""
        use_case = self.provider.build_patch_agent_capabilities_use_case()
        return use_case.execute(command=command)

    def set_ai_kill_switch(self, *, workspace_id: str, enabled: bool, actor: Any, reason: str) -> Any:
        """Flip the workspace AI kill switch (human-only; audited)."""
        use_case = self.provider.build_set_ai_kill_switch_use_case()
        return use_case.execute(workspace_id=workspace_id, enabled=enabled, actor=actor, reason=reason)

    def ai_kill_switch_status(self, *, workspace_id: str) -> Any:
        """Read the kill-switch status (workspace toggle + emergency flag)."""
        from components.agents.application.services import ai_governance_service

        return ai_governance_service.kill_switch_status(str(workspace_id))

    def posture_dashboard(self, *, workspace_id: str, persona: str, window_days: int) -> Any:
        """Compose the chart-ready posture dashboard (HUD POSTURE module)."""
        from components.agents.application.services import posture_dashboard_service

        return posture_dashboard_service.dashboard(str(workspace_id), persona=persona, window_days=window_days)

    def follow_agent(self, command) -> Any:
        """Follow an agent."""
        use_case = self.provider.build_follow_agent_use_case()
        return use_case.execute(command)

    def unfollow_agent(self, command) -> Any:
        """Unfollow an agent."""
        use_case = self.provider.build_unfollow_agent_use_case()
        return use_case.execute(command)

    def like_agent(self, command) -> Any:
        """Like an agent."""
        use_case = self.provider.build_like_agent_use_case()
        return use_case.execute(command)

    def unlike_agent(self, command) -> Any:
        """Unlike an agent."""
        use_case = self.provider.build_unlike_agent_use_case()
        return use_case.execute(command)

    def rate_agent(self, command) -> Any:
        """Rate an agent."""
        use_case = self.provider.build_rate_agent_use_case()
        return use_case.execute(command)

    def comment_agent(self, command) -> Any:
        """Comment on an agent."""
        use_case = self.provider.build_comment_agent_use_case()
        return use_case.execute(command)

    def share_agent(self, command) -> Any:
        """Share an agent."""
        use_case = self.provider.build_share_agent_use_case()
        return use_case.execute(command)

    def revoke_share(self, command) -> Any:
        """Revoke agent share."""
        use_case = self.provider.build_revoke_share_use_case()
        return use_case.execute(command)

    def clear_agent_memory(self, command) -> Any:
        """Clear agent memory."""
        use_case = self.provider.build_clear_agent_memory_use_case()
        return use_case.execute(command)

    def add_system_message(self, command) -> Any:
        """Add system message to agent."""
        use_case = self.provider.build_add_system_message_use_case()
        return use_case.execute(command)

    def update_teammate_profile(self, command) -> Any:
        """Update teammate profile."""
        use_case = self.provider.build_update_teammate_profile_use_case()
        return use_case.execute(command=command)

    def get_teammate_profile(self, query) -> Any:
        """Get teammate profile."""
        use_case = self.provider.build_get_teammate_profile_use_case()
        return use_case.execute(request=query)

    # ── Query methods ───────────────────────────────────────────────────────────

    def list_agents(self, query) -> Any:
        """List all agents."""
        query_obj = self.provider.build_list_agents_query()
        return query_obj.execute(request=query)

    def list_agent_types(self, query) -> Any:
        """List agent types."""
        query_obj = self.provider.build_list_agent_types_query()
        return query_obj.execute(request=query)

    def get_agent_state(self, query) -> Any:
        """Get agent state (query variant)."""
        query_obj = self.provider.build_get_agent_state_query()
        return query_obj.execute(request=query)

    def get_agent_profile(self, query) -> Any:
        """Get agent profile (query variant)."""
        query_obj = self.provider.build_get_agent_profile_query()
        return query_obj.execute(request=query)

    def workspace_search(self, query) -> Any:
        """Search workspace."""
        query_obj = self.provider.build_workspace_search_query()
        return query_obj.execute(query)

    def agent_graph(self, query, http_request=None) -> Any:
        """Fetch agent graph."""
        query_obj = self.provider.build_agent_graph_query()
        return query_obj.execute(request=query, http_request=http_request)

    def execution_detail(self, query) -> Any:
        """Fetch execution detail."""
        query_obj = self.provider.build_execution_detail_query()
        return query_obj.execute(request=query)

    def execution_list(self, query) -> Any:
        """Fetch execution list."""
        query_obj = self.provider.build_execution_list_query()
        return query_obj.execute(request=query)

    def agent_memory(self, query) -> Any:
        """Fetch agent memory."""
        query_obj = self.provider.build_agent_memory_query()
        return query_obj.execute(request=query)

    def agent_ratings(self, query, http_request=None) -> Any:
        """Fetch agent ratings."""
        query_obj = self.provider.build_agent_ratings_query()
        return query_obj.execute(request=query, http_request=http_request)

    def agent_comments(self, query, http_request=None) -> Any:
        """Fetch agent comments."""
        query_obj = self.provider.build_agent_comments_query()
        return query_obj.execute(request=query, http_request=http_request)

    def shared_agent(self, query) -> Any:
        """Fetch shared agent."""
        query_obj = self.provider.build_shared_agent_query()
        return query_obj.execute(request=query)

    # ── Cross-context queries (via ports) ─────────────────────────────────────────

    def get_team_by_id(self, team_id: str, active_only: bool = True):
        return self.provider.build_team_query().get_by_id(team_id, active_only=active_only)

    def get_project_by_id(self, project_id: str, team):
        return self.provider.build_project_query().get_project_by_id(project_id, team=team)

    def get_column_by_id(self, column_id: str, team):
        return self.provider.build_project_query().get_column_by_id(column_id, team=team)

    def list_columns(self, *, team, workspace, active_only: bool = True):
        return self.provider.build_project_query().list_columns(
            team=team,
            workspace=workspace,
            active_only=active_only,
        )

    def get_users_by_ids(self, user_ids: list[str]) -> list:
        return self.provider.build_user_query().get_by_ids(user_ids)

    def get_workspace_by_id(self, workspace_id: str):
        return self.provider.build_workspace_query().get_by_id(workspace_id)

    def get_conversation_by_id(self, conversation_id: str, user):
        return self.provider.build_conversation_repository().get_by_id(conversation_id, user=user)

    def list_conversations_for_user(self, user):
        return self.provider.build_conversation_repository().list_for_user(user)

    def get_file_by_id(self, file_id: str, owner):
        return self.provider.build_file_repository().get_by_id(file_id, owner=owner)

    def update_file_status(self, file, *, status: str):
        return self.provider.build_file_repository().update_processing_status(file, status=status)

    def create_conversation(self, **kwargs):
        return self.provider.build_conversation_repository().create(**kwargs)

    def delete_conversation(self, conversation_id: str, *, user) -> bool:
        return self.provider.build_conversation_repository().delete(conversation_id, user=user)

    def clear_conversation_messages(self, conversation_id: str, *, user) -> bool:
        return self.provider.build_conversation_repository().clear_messages(conversation_id, user=user)

    def create_message(self, *, conversation, role: str, content: str, **kwargs):
        return self.provider.build_conversation_message_repository().create_message(
            conversation=conversation,
            role=role,
            content=content,
            **kwargs,
        )

    # ── Document-assist threads ──
    # The in-editor "AI assist" on a draft/newsletter reuses the SAME
    # Conversation + ConversationMessage + AgentResponseFeedback stack as
    # human chat (per-user, marked ``surface='document_assist'``), so the
    # thread survives close/reopen, thumbs up/down work through the existing
    # message-feedback endpoint, and published documents can show what the
    # AI did read-only — all without a parallel system.

    def find_document_assist_conversation_id(self, *, user, artifact_type: str, artifact_id: str):
        conversation = self.provider.build_conversation_repository().find_document_assist(
            user=user, artifact_type=artifact_type, artifact_id=str(artifact_id)
        )
        return str(conversation.id) if conversation is not None else None

    def record_document_assist_turn(
        self,
        *,
        user,
        artifact_type: str,
        artifact_id: str,
        title: str,
        prompt: str,
        response_text: str,
        response_metadata: dict | None = None,
    ) -> dict:
        repo = self.provider.build_conversation_repository()
        conversation = repo.find_document_assist(user=user, artifact_type=artifact_type, artifact_id=str(artifact_id))
        if conversation is None:
            conversation = repo.create(
                user=user,
                title=(title or "Document assist")[:255],
                metadata={
                    "surface": "document_assist",
                    "artifact_type": artifact_type,
                    "artifact_id": str(artifact_id),
                },
            )
        msg_repo = self.provider.build_conversation_message_repository()
        msg_repo.create_message(conversation=conversation, role="human", content=prompt or "")
        assistant = msg_repo.create_message(
            conversation=conversation,
            role="assistant",
            content=response_text or "",
            metadata=response_metadata or {},
        )
        return {
            "conversation_id": str(conversation.id),
            "assistant_message_id": str(assistant.id),
        }

    def update_message_streaming(self, message, *, content: str, is_streaming: bool):
        return self.provider.build_conversation_message_repository().update_streaming_status(
            message,
            content=content,
            is_streaming=is_streaming,
        )

    def get_document_with_chunks(self, document_id: str):
        return self.provider.build_document_query().get_with_chunks(document_id)
