"""Provider for the project soft-delete adapter.

Cross-context callers (recycle_bin) consume this provider instead of importing
``components.project.infrastructure.adapters.project_soft_delete_adapter``
directly.
"""

from __future__ import annotations

from typing import Any


class ProjectSoftDeleteProvider:
    def adapter(self) -> Any:
        from components.project.infrastructure.adapters.project_soft_delete_adapter import (
            ProjectSoftDeleteAdapter,
        )

        return ProjectSoftDeleteAdapter()

    def task_adapter(self) -> Any:
        from components.project.infrastructure.adapters.task_soft_delete_adapter import (
            TaskSoftDeleteAdapter,
        )

        return TaskSoftDeleteAdapter()

    def column_adapter(self) -> Any:
        from components.project.infrastructure.adapters.column_soft_delete_adapter import (
            ColumnSoftDeleteAdapter,
        )

        return ColumnSoftDeleteAdapter()


_default = ProjectSoftDeleteProvider()


def get_project_soft_delete_provider() -> ProjectSoftDeleteProvider:
    return _default
