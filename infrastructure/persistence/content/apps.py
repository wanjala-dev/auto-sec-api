from django.apps import AppConfig


class ContentPersistenceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'infrastructure.persistence.content'
    verbose_name = "Content (Newsletters, Drafts, Templates)"

    def ready(self) -> None:
        # Celery task autodiscover shim — re-export tasks living in the
        # component layer so the worker picks them up.
        try:
            from components.content.workers import tasks as _content_tasks  # noqa: F401
        except ImportError:
            # The workers/tasks.py exists today as an empty stub; the
            # try/except keeps app boot resilient while Phase 6 wiring
            # is still in flight.
            pass

        # RAG indexing handlers — subscribe NewsletterSent +
        # WritingDraftPublished to the workspace knowledge corpus so the
        # writing_agent's retrieval tools can surface prior issues +
        # past letters during composition. Both gated by
        # ``feature.writing_rag_indexing`` (per-workspace opt-in until
        # GA so prod embedding spend stays bounded).
        try:
            from components.content.application.handlers.rag_index_newsletter_handler import (
                on_newsletter_sent_index_rag,
            )
            from components.content.application.handlers.rag_index_writing_draft_handler import (
                on_writing_draft_published_index_rag,
            )
            from components.content.domain.events.newsletter_sent_event import (
                NewsletterSent,
            )
            from components.content.domain.events.writing_draft_published_event import (
                WritingDraftPublished,
            )
            from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
                CeleryEventPublisher,
            )

            publisher = CeleryEventPublisher()
            publisher.subscribe(NewsletterSent, on_newsletter_sent_index_rag)
            publisher.subscribe(
                WritingDraftPublished, on_writing_draft_published_index_rag
            )
        except ImportError:
            # Defensive: knowledge or shared_kernel may be temporarily
            # unavailable during a partial install. Don't block app
            # boot — the handlers re-register on the next restart.
            pass

        # Phase 5 sign-off retrofit: register the read-side newsletter +
        # writing-draft adapters with the kernel so the unified sign-off queue
        # can surface them alongside financial reports + workflow emails. This
        # is read-only — it does NOT change how newsletters/drafts are sent or
        # published (their existing human Send/Publish gates are untouched).
        from components.content.application.providers.content_sign_off_provider import (
            get_content_sign_off_provider,
        )

        get_content_sign_off_provider().register_adapters()
