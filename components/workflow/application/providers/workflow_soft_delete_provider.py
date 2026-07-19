"""Provider for the workflow soft-delete adapter.

Cross-context callers (recycle_bin) consume this provider instead of importing
``components.workflow.infrastructure.adapters.workflow_soft_delete_adapter``
directly.
"""

from __future__ import annotations

from typing import Any


class WorkflowSoftDeleteProvider:
    def adapter(self) -> Any:
        from components.workflow.infrastructure.adapters.workflow_soft_delete_adapter import (
            WorkflowSoftDeleteAdapter,
        )

        return WorkflowSoftDeleteAdapter()


_default = WorkflowSoftDeleteProvider()


def get_workflow_soft_delete_provider() -> WorkflowSoftDeleteProvider:
    return _default
