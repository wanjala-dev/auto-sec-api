from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.ai"

    def ready(self):
        # ── Knowledge-context signal handlers (Workspace index rebuild)
        # are still classic Django ORM signals; they don't go through the
        # event publisher.
        from components.knowledge.application.providers.workspace_index_signal_provider import (
            WorkspaceIndexSignalProvider,
        )

        WorkspaceIndexSignalProvider().register_signal_handlers()

        # ── Domain-event subscriptions are declared with
        # ``@subscribes_to(EventClass)`` directly on handler functions in each
        # context's ``application/handlers`` package. This app is the composition
        # root for event wiring: it owns the list of handler packages and binds
        # every collected subscription to the publisher in one call. The registry
        # itself lives in the shared kernel, so a context that adds handlers only
        # declares the decorator and gets its package listed here — it never
        # couples to another context.
        #
        # Adding a handler to a listed context requires no edit here — drop a new
        # ``*_handler.py`` and the registry picks it up at the next boot. Adding a
        # NEW context's first handler package is the only edit this file needs.
        from components.shared_kernel.application.subscription_registry import (
            SubscriptionRegistry,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        SubscriptionRegistry.bind_all(
            CeleryEventPublisher(),
            packages=(
                "components.agents.application.handlers",
                "components.findings.application.handlers",
                "components.integrations.application.handlers",
            ),
        )

        # ── Phase 7.1 — publish DeepRunLog rows to the realtime event
        # layer so the frontend can render agent-run progress live instead
        # of polling. Best-effort; the bridge no-ops when the realtime
        # layer is disabled. Uses Django ORM signals, not the event
        # publisher, so it stays out of the SubscriptionRegistry.
        from components.agents.infrastructure.adapters.deep_run_realtime_signal_bridge import (
            DjangoDeepRunRealtimeSignalBridge,
        )

        DjangoDeepRunRealtimeSignalBridge.register()
