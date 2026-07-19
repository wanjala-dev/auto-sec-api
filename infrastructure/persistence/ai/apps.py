from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'infrastructure.persistence.ai'

    def ready(self):
        # ── Knowledge-context signal handlers (Workspace index rebuild)
        # are still classic Django ORM signals; they don't go through the
        # event publisher.
        from components.knowledge.application.providers.workspace_index_signal_provider import (
            WorkspaceIndexSignalProvider,
        )

        WorkspaceIndexSignalProvider().register_signal_handlers()

        # ── Phase 3 of the Agents-as-Teammates migration (Action List
        # P1 #14) — domain-event subscriptions are declared with
        # ``@subscribes_to(EventClass)`` directly on the handler function.
        # ``SubscriptionRegistry.bind_all`` auto-discovers every handler
        # module under ``components/agents/application/handlers/`` and
        # registers each subscription with the event publisher in one
        # call.
        #
        # Adding a new specialist no longer requires editing this file —
        # drop a new ``*_handler.py`` next to the existing ones and the
        # registry picks it up at the next process boot. This is the
        # piece that unblocks items 20-24 (the 5 specialist agents).
        from components.agents.application.subscription_registry_service import (
            SubscriptionRegistry,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        SubscriptionRegistry.bind_all(CeleryEventPublisher())

        # ── Phase 7.1 — publish DeepRunLog rows to the realtime event
        # layer so the frontend can render agent-run progress live instead
        # of polling. Best-effort; the bridge no-ops when the realtime
        # layer is disabled. Uses Django ORM signals, not the event
        # publisher, so it stays out of the SubscriptionRegistry.
        from components.agents.infrastructure.adapters.deep_run_realtime_signal_bridge import (
            DjangoDeepRunRealtimeSignalBridge,
        )

        DjangoDeepRunRealtimeSignalBridge.register()
