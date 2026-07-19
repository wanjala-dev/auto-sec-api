"""
Agent Service

Service layer for AI agent management, replacing the factory pattern
with a cleaner service-oriented approach.
"""

from datetime import datetime, timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count

from components.agents.application.config.agent_defaults import DEFAULT_AGENT_TYPES
from components.agents.domain.services.agent_config_service import (
    AgentConfigService,
    AgentTypeConfig,
)
from components.agents.infrastructure.adapters.actions.detectors import registry as detector_registry
from components.agents.infrastructure.adapters.langchain.base import AgentRegistry, BaseAgent
from components.agents.infrastructure.adapters.langchain.memory_service import AgentMemoryService
from components.agents.infrastructure.services.actions_service import get_ai_action_service
from infrastructure.persistence.ai.agents.models import Agent, AgentExecution, AgentType

User = get_user_model()


_MAX_ACTIVE_AGENTS = 200  # Prevent unbounded memory growth in long-running workers


class AgentService:
    """Service for managing AI agents with clean separation of concerns"""

    def __init__(self):
        self._active_agents: dict[str, BaseAgent] = {}
        self._agent_type_cache: dict[str, AgentType] = {}
        self._agent_alias_map: dict[str, str] = {}
        self._action_service = get_ai_action_service()

    def _evict_oldest_agents(self) -> None:
        """Evict oldest agents when cache exceeds max size."""
        if len(self._active_agents) <= _MAX_ACTIVE_AGENTS:
            return
        # Remove the oldest entries (first inserted)
        to_remove = len(self._active_agents) - _MAX_ACTIVE_AGENTS
        keys_to_remove = list(self._active_agents.keys())[:to_remove]
        for key in keys_to_remove:
            self._active_agents.pop(key, None)

    def create_agent(
        self,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        *,
        config: dict[str, Any] | None = None,
        department_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new agent instance

        Args:
            agent_type: Type of agent to create ('financial_agent', 'task_agent', etc.)
            user_id: ID of the user creating the agent
            workspace_id: ID of the workspace the agent will work with
            **kwargs: Additional configuration for the agent

        Returns:
            Dictionary with agent information
        """
        # Get user object
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise ValueError(f"User with ID {user_id} not found")

        agent_type_obj = self._get_agent_type(agent_type)
        if not agent_type_obj:
            raise ValueError(f"Unsupported agent type: {agent_type}")

        self._assert_agent_enabled(workspace_id, agent_type_obj.slug)

        merged_config = self._merge_config(agent_type_obj, config)

        self._ensure_registered(agent_type_obj)

        agent_record = Agent.objects.create(
            agent_type=agent_type_obj.slug,
            user=user,
            workspace_id=workspace_id,
            department_id=department_id,
            config=merged_config,
            status="active",
        )

        # Create default profile
        summary, capabilities, _examples = self._extract_profile_details(agent_type_obj)
        default_display_name = f"{agent_type_obj.name} for workspace {workspace_id}"
        from infrastructure.persistence.ai.agents.models import AgentProfile

        AgentProfile.objects.get_or_create(
            agent=agent_record,
            defaults={
                "display_name": default_display_name,
                "summary": summary,
                "tags": capabilities or [],
                "visibility": AgentProfile.VISIBILITY_SEED_ONLY,
            },
        )

        agent = AgentRegistry.create_agent(
            name=agent_type_obj.slug,
            agent_id=str(agent_record.agent_id),
            user_id=user_id,
            workspace_id=workspace_id,
            **merged_config,
        )

        # Store active agent in memory for current session (with eviction)
        self._active_agents[str(agent_record.agent_id)] = agent
        self._evict_oldest_agents()

        # Refresh to capture any updates performed while initialising memory (e.g. conversation_id)
        try:
            agent_record.refresh_from_db()
        except Exception:
            pass

        return self._serialize_agent(agent_record)

    def get_or_create_agent(
        self,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        *,
        config: dict[str, Any] | None = None,
        department_id: str | None = None,
    ) -> dict[str, Any]:
        """Return an existing agent for the user/workspace or create a new one."""

        agent_type_obj = self._get_agent_type(agent_type)
        if not agent_type_obj:
            raise ValueError(f"Unsupported agent type: {agent_type}")

        canonical_type = agent_type_obj.slug

        self._assert_agent_enabled(workspace_id, canonical_type)

        existing_queryset = Agent.objects.filter(
            agent_type=canonical_type, user_id=user_id, workspace_id=workspace_id
        ).exclude(status="deleted")
        if department_id:
            existing_queryset = existing_queryset.filter(department_id=department_id)
        else:
            existing_queryset = existing_queryset.filter(department_id__isnull=True)
        existing = existing_queryset.order_by("-created_at").first()

        if existing:
            agent_id = str(existing.agent_id)
            if config:
                merged = dict(existing.config or {})
                merged.update(config)
                if merged != existing.config:
                    existing.config = merged
                    existing.updated_at = datetime.now()
                    existing.save(update_fields=["config", "updated_at"])
                if agent_id in self._active_agents:
                    try:
                        self._active_agents[agent_id].config.update(config)
                    except Exception:
                        pass
            if agent_id not in self._active_agents:
                self._ensure_registered(agent_type_obj)
                self._active_agents[agent_id] = self._build_agent_instance(existing)
            return self._serialize_agent(existing)

        return self.create_agent(
            agent_type=canonical_type,
            user_id=user_id,
            workspace_id=workspace_id,
            config=config or {},
            department_id=department_id,
        )

    def get_agent(self, agent_id: str) -> BaseAgent | None:
        """Get an active agent by ID"""
        if agent_id in self._active_agents:
            return self._active_agents[agent_id]

        agent_record = self._get_agent_record(agent_id)
        if not agent_record:
            return None

        agent_instance = self._build_agent_instance(agent_record)
        if agent_instance:
            self._active_agents[agent_id] = agent_instance
        return agent_instance

    def execute_agent(
        self,
        agent_id: str,
        query: str,
        *,
        performed_by: str | None = None,
        context: dict[str, Any] | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a query with the specified agent.

        If the agent's stored config has ``mode == "deep"`` (or the call
        site passes ``context["mode"] == "deep"``), we route through the
        LangGraph deep-agent pipeline (`deep.runner.execute_plan_once`)
        instead of the legacy ReAct executor. The deep path produces a
        structured plan, fans out workers, and persists a `DeepRun`
        ledger with checkpoints — see ADR / DEEP_AGENTS.md.
        """
        agent_record = self._get_agent_record(agent_id)
        if not agent_record:
            raise ValueError(f"Agent {agent_id} not found or not active")

        self._assert_agent_enabled(str(agent_record.workspace_id), str(agent_record.agent_type))

        agent_config = dict(getattr(agent_record, "config", None) or {})
        ctx = dict(context or {})
        mode = (ctx.get("mode") or agent_config.get("mode") or "").lower()
        if mode == "deep":
            return self._execute_deep(
                agent_record=agent_record,
                agent_config=agent_config,
                query=query,
                performed_by=performed_by,
                context=ctx,
            )

        agent = self.get_agent(agent_id)
        if not agent:
            agent = self._build_agent_instance(agent_record)
            self._active_agents[agent_id] = agent

        # Per-call conversation override. The agent's MemoryService
        # resolves `agent.config['conversation_id']` lazily, so swapping
        # it for the duration of the call lets the same agent serve
        # multiple parallel chat threads. Restore in finally so a
        # crash doesn't leak the override into subsequent calls.
        previous_conv_id = None
        override_conv = False
        if conversation_id:
            previous_conv_id = (agent.config or {}).get("conversation_id")
            agent.config = agent.config or {}
            agent.config["conversation_id"] = str(conversation_id)
            override_conv = True
        try:
            result = agent.execute(
                query,
                performed_by=performed_by,
                context=context,
            )
            # Surface the conversation_id the memory service ended up
            # using so the chat use case can return it to the frontend.
            # The frontend captures it on the first response and sends
            # it back on subsequent messages to thread them.
            try:
                resolved_conv_id = agent.memory_service.get_conversation_id()
                if isinstance(result, dict) and resolved_conv_id:
                    result.setdefault("conversation_id", str(resolved_conv_id))
            except Exception:  # pragma: no cover - best effort
                logger.debug("Could not resolve conversation_id for response", exc_info=True)
            return result
        finally:
            if override_conv:
                if previous_conv_id is None:
                    agent.config.pop("conversation_id", None)
                else:
                    agent.config["conversation_id"] = previous_conv_id

    def _execute_deep(
        self,
        *,
        agent_record,
        agent_config: dict[str, Any],
        query: str,
        performed_by: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a query through the LangGraph deep-agent pipeline."""
        import uuid as _uuid

        from components.agents.application.services.deep_run_context import (
            DeepRunContext,
            DeepRunContextOptions,
        )
        from components.agents.infrastructure.adapters.deep_run_log_observability_adapter import (
            DeepRunLogObservabilityAdapter,
        )
        from components.agents.infrastructure.adapters.langchain.deep.llm_planner import (
            plan_with_llm,
        )
        from components.agents.infrastructure.adapters.langchain.deep.runner import (
            execute_plan_once,
        )

        plan_id = context.get("plan_id") or str(_uuid.uuid4())
        thread_id = context.get("thread_id") or plan_id

        # A caller may PIN the worker (context/config ``worker_agent_type``).
        # When pinned, it becomes a deterministic forced worker (the planner
        # cannot re-route away from it — see execute_plan_once). When absent, we
        # fall back to the agent's own type as the per-task default and let the
        # planner route freely (the interactive path).
        pinned_worker_agent_type = context.get("worker_agent_type") or agent_config.get("worker_agent_type")
        worker_agent_type = pinned_worker_agent_type or str(agent_record.agent_type)

        # Verification loop (L2): a caller (e.g. the finding router) may request
        # ``max_reflections`` so critic-enabled workers self-verify. Default 0 =
        # off (interactive path unchanged). The critic only grades
        # CRITIC_ENABLED_AGENTS, so passing >0 is a no-op for other workers.
        try:
            max_reflections = int(context.get("max_reflections") or agent_config.get("max_reflections") or 0)
        except (TypeError, ValueError):
            max_reflections = 0

        # Build the DeepRunContext for this run. The runner threads it
        # to the worker factory as a CLOSURE kwarg (not on the
        # JSON-serialised ``run_context``, which LangGraph checkpoints
        # at every node transition — a live DeepRunContext holding an
        # observability adapter cannot round-trip through JSON). The
        # adapter then attaches it to the request-local context dict
        # passed into ``service.execute_agent``, where ``BaseAgent.execute``
        # picks it up as ``self._active_deep_run_context`` for the call
        # duration. Tool closures emit through it via ``ctx.info()`` /
        # ``ctx.report_progress()``; the existing realtime signal bridge
        # forwards each DeepRunLog row to the per-run WebSocket channel.
        # See docs/plans/CHAT_LOG_AND_PROGRESS_NOTIFICATIONS_PLAN.md
        # Phase 1 + Phase 2.
        deep_run_context = DeepRunContext(
            DeepRunLogObservabilityAdapter(),
            DeepRunContextOptions(
                thread_id=thread_id,
                default_agent_type=worker_agent_type,
                default_tool_name=None,
            ),
        )

        plan = plan_with_llm(
            goal=query,
            plan_id=plan_id,
            workspace_id=str(agent_record.workspace_id),
            team_id=context.get("team_id"),
            model_name=agent_config.get("model_name"),
            extra_context=context,
        )

        state = execute_plan_once(
            plan,
            agent_type=worker_agent_type,
            user_id=performed_by or str(agent_record.user_id),
            workspace_id=str(agent_record.workspace_id),
            agent_config=agent_config,
            thread_id=thread_id,
            deep_run_context=deep_run_context,
            force_worker_agent_type=pinned_worker_agent_type,
            max_reflections=max_reflections,
        )
        final = state.get("final_output") if isinstance(state, dict) else None
        answer = None
        if isinstance(final, dict):
            answer = final.get("answer") or final.get("completed_tasks")
        return {
            "success": True,
            "result": answer or "Deep run completed.",
            "plan_id": plan_id,
            "thread_id": context.get("thread_id") or plan_id,
            "final_output": final,
            "mode": "deep",
        }

    def execute_agent_async(
        self,
        agent_id: str,
        query: str,
        *,
        user_id: str = None,
        context: dict[str, Any] | None = None,
    ) -> AgentExecution:
        """Schedule agent execution as a Celery task"""
        agent_record = self._get_agent_record(agent_id)
        if not agent_record:
            raise ValueError(f"Agent {agent_id} not found")

        self._assert_agent_enabled(str(agent_record.workspace_id), str(agent_record.agent_type))

        if user_id and str(agent_record.user_id) != str(user_id):
            user = User.objects.filter(id=user_id).first()
            if not user:
                raise PermissionError("User does not have access to this agent")
            workspace = agent_record.workspace
            if not workspace:
                raise PermissionError("User does not have access to this agent")
            from components.workspace.application.facades.workspace_facade import user_is_workspace_member

            if not user_is_workspace_member(user, workspace):
                raise PermissionError("User does not have access to this agent")

        agent_type_obj = self._get_agent_type(agent_record.agent_type)
        if not agent_type_obj:
            raise ValueError(f"Agent type {agent_record.agent_type} is not registered")
        self._ensure_registered(agent_type_obj)

        initial_state = {"status": AgentExecution.STATUS_PENDING}
        if context:
            initial_state["context"] = context

        execution = AgentExecution.objects.create(
            agent=agent_record,
            query=query,
            status=AgentExecution.STATUS_PENDING,
            success=True,
            progress=0,
            state=initial_state,
            triggered_by_id=user_id,
        )

        # Prime memory with the user query for conversational continuity
        memory_service = AgentMemoryService(str(agent_record.agent_id))
        memory_service.add_user_message(query)

        # Import task lazily to avoid circular imports at module load
        from components.agents.infrastructure.tasks.agent_tasks import run_agent_execution

        try:
            task = run_agent_execution.delay(str(execution.id))
        except Exception as exc:  # pylint: disable=broad-except
            execution.status = AgentExecution.STATUS_FAILED
            execution.success = False
            execution.error_message = str(exc)
            execution.progress = 100
            execution.state = {
                "status": AgentExecution.STATUS_FAILED,
                "error": str(exc),
            }
            execution.save(update_fields=["status", "success", "error_message", "progress", "state"])
            raise

        execution.task_id = task.id or ""
        execution.save(update_fields=["task_id"])

        return execution

    def list_user_agents(self, user_id: str) -> list[dict[str, Any]]:
        """Get all agents for a specific user"""
        agents = (
            Agent.objects.filter(user_id=user_id)
            .select_related("user", "profile", "workspace")
            .annotate(
                followers_count=Count("follows", distinct=True),
                likes_count=Count("reactions", distinct=True),
                rating_avg=Avg("ratings__score"),
                rating_count=Count("ratings", distinct=True),
                comment_count=Count("comments", distinct=True),
            )
        )
        return [self._serialize_agent(agent) for agent in agents]

    def list_workspace_agents(self, workspace_id: str) -> list[dict[str, Any]]:
        """Get all agents for a specific workspace"""
        agents = (
            Agent.objects.filter(workspace_id=workspace_id)
            .select_related("user", "profile", "workspace")
            .annotate(
                followers_count=Count("follows", distinct=True),
                likes_count=Count("reactions", distinct=True),
                rating_avg=Avg("ratings__score"),
                rating_count=Count("ratings", distinct=True),
                comment_count=Count("comments", distinct=True),
            )
        )
        return [self._serialize_agent(agent) for agent in agents]

    def list_user_workspace_agents(self, user_id: str, workspace_id: str) -> list[dict[str, Any]]:
        """Get all agents for a specific user and workspace"""
        agents = (
            Agent.objects.filter(user_id=user_id, workspace_id=workspace_id)
            .select_related("user", "profile", "workspace")
            .annotate(
                followers_count=Count("follows", distinct=True),
                likes_count=Count("reactions", distinct=True),
                rating_avg=Avg("ratings__score"),
                rating_count=Count("ratings", distinct=True),
                comment_count=Count("comments", distinct=True),
            )
        )
        return [self._serialize_agent(agent) for agent in agents]

    def pause_agent(self, agent_id: str) -> bool:
        """Pause an agent"""
        agent = self.get_agent(agent_id)
        if agent:
            agent.pause()
            # Update database status
            Agent.objects.filter(agent_id=agent_id).update(status="paused")
            return True
        return False

    def resume_agent(self, agent_id: str) -> bool:
        """Resume an agent"""
        agent = self.get_agent(agent_id)
        if agent:
            agent.resume()
            # Update database status
            Agent.objects.filter(agent_id=agent_id).update(status="active")
            return True
        return False

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent"""
        # Remove from active agents
        if agent_id in self._active_agents:
            del self._active_agents[agent_id]

        # Update database status
        updated = Agent.objects.filter(agent_id=agent_id).update(status="deleted")
        return updated > 0

    def remove_agent(self, agent_id: str) -> bool:
        """Compatibility alias for delete_agent"""
        return self.delete_agent(agent_id)

    def get_agent_memory_service(self, agent_id: str) -> AgentMemoryService:
        """Get memory service for an agent"""
        return AgentMemoryService(agent_id)

    def ensure_teammate_agent(self, workspace_id: str) -> dict[str, Any]:
        """Ensure the AI teammate agent exists for a workspace and return its record."""
        from infrastructure.persistence.workspaces.models import (
            Workspace,
        )  # Local import to avoid circular dependency at load time

        workspace_queryset = getattr(Workspace, "_base_manager", None) or Workspace.objects
        workspace = workspace_queryset.get(id=workspace_id)
        profile = self._action_service.ensure_teammate(workspace)
        config = dict(profile.config or {})
        config.setdefault("detectors", [])
        if profile.display_name:
            config["display_name"] = profile.display_name
            profile_config = config.setdefault("profile", {})
            profile_config.setdefault("name", profile.display_name)
        return self.get_or_create_agent(
            agent_type="ai_teammate",
            user_id=str(profile.user_id),
            workspace_id=str(workspace.id),
            config=config,
        )

    def register_teammate_detector(self, detector_cls):
        """Register a detector for teammate orchestration."""
        return detector_registry.register(detector_cls)

    def list_teammate_detectors(self) -> list[str]:
        """List registered teammate detectors."""
        return list(detector_registry.list_slugs())

    def _get_agent_record(self, agent_id: str) -> Agent | None:
        try:
            return Agent.objects.get(agent_id=agent_id)
        except Agent.DoesNotExist:
            return None

    def _build_agent_instance(self, agent_record: Agent) -> BaseAgent:
        agent_type_obj = self._get_agent_type(agent_record.agent_type)
        if not agent_type_obj:
            raise ValueError(f"Unknown agent type for record {agent_record.agent_id}")

        merged_config = self._merge_config(agent_type_obj, agent_record.config)
        if agent_record.department_id:
            merged_config.setdefault("department_id", str(agent_record.department_id))
        self._ensure_registered(agent_type_obj)

        agent = AgentRegistry.create_agent(
            name=agent_type_obj.slug,
            agent_id=str(agent_record.agent_id),
            user_id=str(agent_record.user_id),
            workspace_id=str(agent_record.workspace_id),
            **merged_config,
        )
        return agent

    def cleanup_inactive_agents(self, max_age_hours: int = 24) -> int:
        """Clean up agents that haven't been used recently"""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

        inactive_agents = []
        for agent_id, agent in self._active_agents.items():
            if agent.state.updated_at < cutoff_time:
                inactive_agents.append(agent_id)

        for agent_id in inactive_agents:
            del self._active_agents[agent_id]

        return len(inactive_agents)

    def list_available_agent_types(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        """Return catalogue of agent types"""
        self._load_agent_types(force_refresh=True)
        qs = AgentType.objects.all()
        if not include_inactive:
            qs = qs.filter(is_active=True)

        catalogue = []
        for agent_type in qs.order_by("name"):
            self._ensure_registered(agent_type)
            summary, capabilities, examples = self._extract_profile_details(agent_type)
            catalogue.append(
                {
                    "slug": agent_type.slug,
                    "name": agent_type.name,
                    "description": agent_type.description,
                    "summary": summary,
                    "capabilities": capabilities,
                    "examples": examples,
                    "class_path": agent_type.class_path,
                    "aliases": agent_type.aliases,
                    "default_config": agent_type.default_config,
                    "required_actions": agent_type.required_actions,
                    "allowed_tools": agent_type.allowed_tools,
                    "department_tags": agent_type.department_tags,
                    "default_run_config": agent_type.default_run_config,
                    "is_active": agent_type.is_active,
                }
            )
        return catalogue

    def list_workspace_agent_types(self, workspace_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
        """Return catalogue annotated with workspace enablement state."""
        from components.agents.application.policies.agent_entitlements import (
            get_workspace_entitlement_map,
            workspace_ai_enabled,
        )

        self._load_agent_types(force_refresh=True)
        catalogue = self.list_available_agent_types(include_inactive=include_inactive)
        entitlements = get_workspace_entitlement_map(workspace_id)
        ai_enabled = workspace_ai_enabled(workspace_id)

        for entry in catalogue:
            slug = entry.get("slug")
            entitlement = entitlements.get(slug)
            if ai_enabled and slug == "ai_teammate":
                is_enabled = True
            else:
                is_enabled = bool(ai_enabled and entitlement and entitlement.is_enabled)
            entry["is_enabled"] = is_enabled
            entry["entitlement_id"] = str(entitlement.id) if entitlement else None
            entry["ai_enabled"] = ai_enabled
        return catalogue

    def is_valid_agent_type(self, agent_type: str) -> bool:
        return self._get_agent_type(agent_type) is not None

    def _serialize_agent(self, agent: Agent) -> dict[str, Any]:
        data = agent.to_dict()
        agent_type = self._get_agent_type(agent.agent_type)
        if agent_type:
            data["agent_type_label"] = agent_type.name
            data["agent_type_slug"] = agent_type.slug
        config = data.get("config") or {}
        conversation_id = config.get("conversation_id")
        if not conversation_id:
            try:
                memory_service = self.get_agent_memory_service(str(agent.agent_id))
                conversation_id = memory_service.get_conversation_id()
            except Exception:
                conversation_id = None
        data["conversation_id"] = conversation_id
        profile = getattr(agent, "profile", None)
        if profile:
            data["profile"] = {
                "display_name": profile.display_name,
                "summary": profile.summary,
                "avatar_url": profile.avatar_url,
                "tags": profile.tags or [],
                "visibility": profile.visibility,
                "allow_followers": profile.allow_followers,
                "allow_ratings": profile.allow_ratings,
                "allow_comments": profile.allow_comments,
                "is_disabled": profile.is_disabled,
            }
            data["is_disabled"] = profile.is_disabled
        else:
            data["profile"] = None
            data["is_disabled"] = False
        data["engagement_counts"] = {
            "likes": getattr(agent, "likes_count", 0) or 0,
            "followers": getattr(agent, "followers_count", 0) or 0,
            "rating_avg": float(getattr(agent, "rating_avg", 0) or 0),
            "rating_count": getattr(agent, "rating_count", 0) or 0,
            "comment_count": getattr(agent, "comment_count", 0) or 0,
        }
        custom_profile = (agent.config or {}).get("custom_profile") if isinstance(agent.config, dict) else {}
        if isinstance(custom_profile, dict):
            data["profile_config"] = {
                "persona": custom_profile.get("persona"),
                "tone": custom_profile.get("tone"),
                "tool_whitelist": custom_profile.get("tool_whitelist") or [],
                "output_format": custom_profile.get("output_format"),
                "default_report_period": custom_profile.get("default_report_period"),
            }
        else:
            data["profile_config"] = {}
        if agent.workspace_id:
            try:
                from components.agents.application.policies.agent_entitlements import is_agent_enabled_for_workspace

                data["is_enabled"] = is_agent_enabled_for_workspace(str(agent.workspace_id), agent.agent_type)
            except Exception:
                data["is_enabled"] = False
        return data

    @staticmethod
    def _assert_agent_enabled(workspace_id: str, agent_type: str) -> None:
        from components.agents.application.policies.agent_entitlements import is_agent_enabled_for_workspace

        if not workspace_id or str(workspace_id).lower() == "none":
            return
        if not is_agent_enabled_for_workspace(workspace_id, agent_type):
            raise PermissionError(f"Agent type '{agent_type}' is not enabled for this organization.")

    @staticmethod
    def _extract_profile_details(agent_type: AgentType) -> tuple[str, list[str], list[str]]:
        atc = AgentService._to_agent_type_config(agent_type)
        details = AgentConfigService.extract_profile_details(atc)
        return details.summary, details.capabilities, details.examples

    def _load_agent_types(self, force_refresh: bool = False) -> None:
        if self._agent_type_cache and not force_refresh:
            return
        if force_refresh:
            self._agent_type_cache = {}
            self._agent_alias_map = {}

        # The code registry (`@register_agent` + each agent's `profile`) is the
        # single source of truth. We project it onto the `AgentType` rows, using
        # `DEFAULT_AGENT_TYPES` only as optional per-slug config OVERRIDES — so a
        # brand-new decorated agent needs zero edits here to become entitled.
        from components.agents.infrastructure.adapters.langchain.agents import (
            discover_agents,
        )
        from components.agents.infrastructure.services.agent_type_sync import (
            sync_agent_types_from_registry,
        )

        discover_agents()  # ensure every @register_agent has fired
        overrides = {d["slug"]: d for d in DEFAULT_AGENT_TYPES}
        sync_agent_types_from_registry(overrides=overrides)

        queryset = AgentType.objects.filter(is_active=True)
        self._agent_type_cache = {obj.slug: obj for obj in queryset}
        self._agent_alias_map = {}
        for obj in queryset:
            for alias in obj.aliases or []:
                self._agent_alias_map[alias] = obj.slug

        for obj in queryset:
            self._ensure_registered(obj)

    def _get_agent_type(self, slug: str) -> AgentType | None:
        self._load_agent_types()
        canonical = self._agent_alias_map.get(slug, slug)
        agent_type = self._agent_type_cache.get(canonical)
        if agent_type:
            return agent_type

        try:
            agent_type = AgentType.objects.get(slug=slug)
        except AgentType.DoesNotExist:
            agent_type = AgentType.objects.filter(aliases__contains=[slug]).first()
            if not agent_type:
                return None

        self._agent_type_cache[agent_type.slug] = agent_type
        for alias in agent_type.aliases or []:
            self._agent_alias_map[alias] = agent_type.slug
        self._ensure_registered(agent_type)
        return agent_type

    def _ensure_registered(self, agent_type: AgentType) -> None:
        try:
            if not AgentRegistry.get_agent_class(agent_type.slug):
                AgentRegistry.register(agent_type.slug, agent_type.class_path)
            for alias in agent_type.aliases or []:
                if not AgentRegistry.get_agent_class(alias):
                    AgentRegistry.register(alias, agent_type.class_path)
        except (ImportError, ModuleNotFoundError) as exc:
            import logging

            logging.getLogger(__name__).warning("Skipping agent type %s: %s", agent_type.slug, exc)

    @staticmethod
    def _to_agent_type_config(agent_type: AgentType) -> AgentTypeConfig:
        """Map an ORM ``AgentType`` to a domain value object."""
        return AgentTypeConfig(
            slug=agent_type.slug,
            name=agent_type.name,
            description=agent_type.description or "",
            default_config=agent_type.default_config or {},
            aliases=agent_type.aliases or [],
            required_actions=agent_type.required_actions or [],
            allowed_tools=agent_type.allowed_tools or [],
            department_tags=agent_type.department_tags or [],
            default_run_config=agent_type.default_run_config or {},
            class_path=agent_type.class_path or "",
            is_active=agent_type.is_active,
        )

    def _merge_config(self, agent_type: AgentType, override: dict[str, Any] | None) -> dict[str, Any]:
        return AgentConfigService.merge_config(
            self._to_agent_type_config(agent_type),
            override,
        )


# Global agent service instance
agent_service = AgentService()


def get_agent_service() -> AgentService:
    """Get the global agent service instance"""
    return agent_service


def register_agent_type(
    *,
    slug: str,
    name: str,
    class_path: str,
    description: str = "",
    aliases: list[str] | None = None,
    default_config: dict[str, Any] | None = None,
    required_actions: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    department_tags: list[str] | None = None,
    default_run_config: dict[str, Any] | None = None,
) -> AgentType:
    """Create or update an AgentType entry for programmatic registrations."""
    return AgentType.objects.update_or_create(
        slug=slug,
        defaults={
            "name": name,
            "description": description or "",
            "class_path": class_path,
            "aliases": aliases or [],
            "default_config": default_config or {},
            "required_actions": required_actions or [],
            "allowed_tools": allowed_tools or [],
            "department_tags": department_tags or [],
            "default_run_config": default_run_config or {},
            "is_active": True,
        },
    )[0]
