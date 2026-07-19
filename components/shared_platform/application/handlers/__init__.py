"""Event handlers for the shared_platform bounded context.

Handlers in this package react to domain and application events,
performing side-effect orchestration (notifications, materialisations,
async processing).  They are registered with the ``EventPublisher``
port during composition-root wiring.

The handler functions are transport-agnostic — they receive a
``DomainEvent`` and orchestrate the response.  Whether the event
was delivered synchronously (``LocalEventPublisher``) or via Celery
(``CeleryEventPublisher``) is invisible to the handler.

Current handlers:
    - process_pdf_file (file upload reaction)
    - process_document_file (file upload reaction)
    - process_pending_pdfs (file upload reaction)
    - send_email_task (contact form)
"""
