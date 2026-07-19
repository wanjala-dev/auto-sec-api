"""Provider/composition root for the contact-email Celery task.

Controllers MUST consume :class:`ContactEmailTaskProvider` instead of
importing
``components.shared_platform.infrastructure.tasks.contact_tasks`` directly.
The arch test ``test_controllers_do_not_import_concrete_adapters``
enforces this.

The provider exposes a single ``delay(...)`` method that lazy-imports the
underlying ``send_email_task`` Celery task and dispatches it. Tests can
monkeypatch this module's ``_default`` to assert dispatch payloads
without standing up a Celery worker.
"""

from __future__ import annotations

from typing import Any


class ContactEmailTaskProvider:
    """Driving-side façade for the contact-us email Celery task."""

    def delay(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.tasks.contact_tasks import (
            send_email_task,
        )

        return send_email_task.delay(*args, **kwargs)


_default = ContactEmailTaskProvider()


def get_contact_email_task_provider() -> ContactEmailTaskProvider:
    """Return the default provider — composition root for the contact-email
    Celery task.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
