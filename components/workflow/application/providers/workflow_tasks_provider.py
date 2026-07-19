"""Provider/composition root for the workflow Celery task surface.

The workflow API controller dispatches Celery tasks (``workflow_run_start``,
``workflow_run_step``, ``workflow_run_branch``, ``workflow_run_complete``) to
advance runs. Importing the concrete ``components.workflow.infrastructure
.tasks.workflow_tasks`` module directly from the controller violates the
Explicit Architecture controller → infrastructure boundary.

This provider exposes one method per dispatch-side operation. Each method
lazy-imports the task symbol and calls ``.delay(…)`` so the controller never
holds a direct reference to the Celery task object. Tests can monkeypatch
``_default`` to stub task scheduling without importing Celery.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class WorkflowTasksProvider:
    """Driving-side façade for workflow Celery task dispatch."""

    def enqueue_run_start(self, run_id: str) -> Any:
        """Enqueue ``workflow_run_start`` for the given run id."""
        from components.workflow.infrastructure.tasks.workflow_tasks import (
            workflow_run_start,
        )

        return workflow_run_start.delay(run_id)

    def enqueue_run_step(self, run_id: str, node_id: str) -> Any:
        """Enqueue ``workflow_run_step`` for the given run + node."""
        from components.workflow.infrastructure.tasks.workflow_tasks import (
            workflow_run_step,
        )

        return workflow_run_step.delay(run_id, node_id)

    def enqueue_run_branch(
        self,
        run_id: str,
        node_id: str,
        output: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Enqueue ``workflow_run_branch`` for the given decision node."""
        from components.workflow.infrastructure.tasks.workflow_tasks import (
            workflow_run_branch,
        )

        return workflow_run_branch.delay(run_id, node_id, output)

    def enqueue_run_complete(self, run_id: str) -> Any:
        """Enqueue ``workflow_run_complete`` for the given run id."""
        from components.workflow.infrastructure.tasks.workflow_tasks import (
            workflow_run_complete,
        )

        return workflow_run_complete.delay(run_id)


_default = WorkflowTasksProvider()


def get_workflow_tasks_provider() -> WorkflowTasksProvider:
    """Return the default provider — composition root for the workflow
    Celery task surface. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
