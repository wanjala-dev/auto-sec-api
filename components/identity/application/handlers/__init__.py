"""Event handlers for the identity bounded context.

Handlers in this package react to domain and application events,
performing side-effect orchestration (notifications, materialisations,
async processing).  They are registered with the ``EventPublisher``
port during composition-root wiring.

The handler functions are transport-agnostic — they receive a
``DomainEvent`` and orchestrate the response.  Whether the event
was delivered synchronously (``LocalEventPublisher``) or via Celery
(``CeleryEventPublisher``) is invisible to the handler.

Current handlers:
    - notify_security_event (security event reaction)
"""
