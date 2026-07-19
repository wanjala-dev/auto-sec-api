"""Provider/composition root for the document-import Celery pipeline.

Controllers MUST consume :class:`DocumentImportTaskProvider` instead of
importing
``components.shared_platform.infrastructure.tasks.document_import_tasks``
directly. The arch test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

Two capabilities are exposed today:

* ``parse_delay(import_id)`` — dispatch the async parse task.
* ``emit_event(doc_import, trigger_type, payload)`` — emit a workflow
  event for document lifecycle transitions.

A :py:func:`parse_delay_callable` helper returns the underlying ``delay``
callable so callers that need to defer dispatch via ``transaction.on_commit``
still have a cheap bound callable to capture.
"""

from __future__ import annotations

from typing import Any, Callable


class DocumentImportTaskProvider:
    """Driving-side façade for the document-import Celery pipeline."""

    def parse_delay(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.tasks.document_import_tasks import (
            document_import_parse,
        )

        return document_import_parse.delay(*args, **kwargs)

    def parse_delay_callable(self) -> Callable[..., Any]:
        """Return the bound ``delay`` callable so callers can defer via
        ``transaction.on_commit(lambda: callable_(pk))`` without an extra
        attribute lookup at commit time."""
        from components.shared_platform.infrastructure.tasks.document_import_tasks import (
            document_import_parse,
        )

        return document_import_parse.delay

    def emit_event(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.tasks.document_import_tasks import (
            _emit_document_event,
        )

        return _emit_document_event(*args, **kwargs)


_default = DocumentImportTaskProvider()


def get_document_import_task_provider() -> DocumentImportTaskProvider:
    """Return the default provider — composition root for the document-import
    Celery pipeline.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
