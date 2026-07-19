"""Provider/composition root for the workflow dispatcher adapter.

Controllers in other bounded contexts (grants, project, and any future
workflow-event emitter) consume :class:`WorkflowDispatcherProvider` instead
of importing the concrete dispatcher adapter directly. This keeps the API
layer's import graph free of infrastructure dependencies — the test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

The provider lazy-imports the adapter inside each method so module load is
cheap and tests can monkeypatch this module's ``_default`` attribute (or the
provider's method) without dragging in Django ORM / Celery at import time.
"""

from __future__ import annotations

from typing import Any


class WorkflowDispatcherProvider:
    """Driving-side façade for the workflow dispatcher adapter."""

    def emit_workflow_event(self, *args, **kwargs) -> Any:
        """Persist a workflow event and enqueue processing after commit.

        Delegates to ``components.workflow.infrastructure.adapters.dispatcher
        .emit_workflow_event``.
        """
        from components.workflow.infrastructure.adapters.dispatcher import (
            emit_workflow_event as _emit_workflow_event,
        )

        return _emit_workflow_event(*args, **kwargs)

    def dispatch_event(self, *args, **kwargs) -> int:
        """Start workflow runs for bindings that match the given event.

        Delegates to ``components.workflow.infrastructure.adapters.dispatcher
        .dispatch_event``.
        """
        from components.workflow.infrastructure.adapters.dispatcher import (
            dispatch_event as _dispatch_event,
        )

        return _dispatch_event(*args, **kwargs)


_default = WorkflowDispatcherProvider()


def get_workflow_dispatcher_provider() -> WorkflowDispatcherProvider:
    """Return the default provider — composition root for the workflow
    dispatcher adapter. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
