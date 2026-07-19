"""Event handlers for the knowledge bounded context.

Handlers in this package react to domain and application events,
performing side-effect orchestration (notifications, materialisations,
async processing).  They are registered with the ``EventPublisher``
port during composition-root wiring.

The handler functions are transport-agnostic — they receive a
``DomainEvent`` and orchestrate the response.  Whether the event
was delivered synchronously (``LocalEventPublisher``) or via Celery
(``CeleryEventPublisher``) is invisible to the handler.

Current handlers:
    - create_embeddings_for_workspace (workspace save reaction)
"""
