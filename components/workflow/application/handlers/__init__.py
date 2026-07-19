"""Event handlers for the workflow bounded context.

Handlers in this package react to domain and application events,
performing side-effect orchestration (notifications, materialisations,
async processing).  They are registered with the ``EventPublisher``
port during composition-root wiring.

The handler functions are transport-agnostic — they receive a
``DomainEvent`` and orchestrate the response.  Whether the event
was delivered synchronously (``LocalEventPublisher``) or via Celery
(``CeleryEventPublisher``) is invisible to the handler.

Current handlers:
    - workflow_run_step (workflow execution chain)
    - workflow_run_branch (workflow execution chain)
    - workflow_run_complete (workflow execution chain)
"""
