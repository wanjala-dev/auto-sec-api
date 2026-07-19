from django.apps import AppConfig


class AgentsCLIConfig(AppConfig):
    name = "components.agents.cli"
    label = "agents_cli"
    verbose_name = "Agents CLI"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # ADR 0003: auto-discover any agent module dropped into
        # `components/agents/infrastructure/adapters/langchain/agents/`
        # so adding a new agent never requires editing base.py.
        # Idempotent — discover_agents has its own guard.
        try:
            from components.agents.infrastructure.adapters.langchain.agents import (
                discover_agents,
            )

            discover_agents()
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Auto-discovery of agent modules failed")

        # Project the code registry onto the AgentType rows so a newly
        # discovered agent is immediately entitlement-resolvable — no
        # DEFAULT_AGENT_TYPES edit, no manual reseed. Guarded: the DB may not be
        # migrated yet at boot (first `migrate`), so a failure here is a no-op,
        # not a crash. The `sync_agent_types` command + the lazy
        # `_load_agent_types` path both re-run it.
        try:
            from components.agents.application.config.agent_defaults import (
                DEFAULT_AGENT_TYPES,
            )
            from components.agents.infrastructure.services.agent_type_sync import (
                sync_agent_types_from_registry,
            )

            sync_agent_types_from_registry(overrides={d["slug"]: d for d in DEFAULT_AGENT_TYPES})
        except Exception:
            import logging

            logging.getLogger(__name__).debug(
                "AgentType sync deferred (DB not ready at boot) — will run lazily", exc_info=True
            )

        # Register the AI-teammate Celery tasks (run_ai_teammate_cycle +
        # schedule_ai_teammate_runs — the SOC detect→triage pipeline driver).
        # This module imports ORM models at module level, so it can't be
        # eager-imported in api/celery.py (which runs before the app registry).
        # ready() runs after the registry is populated, so importing it here is
        # safe and registers the @shared_task functions with the Celery app.
        try:
            import components.agents.infrastructure.tasks.agent_tasks  # noqa: F401
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Failed to register AI teammate Celery tasks (agent_tasks)")

        # Wire ``DeepRunLog.post_save`` → publish to Channels.
        # Without this the realtime adapter is dead code: every
        # ``log_deep_event(...)`` call writes a row, no one publishes
        # the event to the WS, and the per-run progress UI sits
        # empty because the WebSocket never receives anything. The
        # bridge has been in the tree since Phase 7.1 of realtime
        # observability — it just was never registered. Caught
        # 2026-05-08 when Henry's chat showed "Waiting for run to
        # start…" forever despite the run completing successfully.
        try:
            from components.agents.infrastructure.adapters.deep_run_realtime_signal_bridge import (
                DjangoDeepRunRealtimeSignalBridge,
            )

            DjangoDeepRunRealtimeSignalBridge.register()
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Failed to register DjangoDeepRunRealtimeSignalBridge — deep-run realtime events will not flow"
            )
