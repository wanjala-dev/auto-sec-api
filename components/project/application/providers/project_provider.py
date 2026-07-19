"""Composition root for project/task operations in the project bounded context."""

from __future__ import annotations

from components.project.application.use_cases.batch_move_tasks_use_case import BatchMoveTasksUseCase
from components.project.application.use_cases.create_project_use_case import CreateProjectUseCase
from components.project.application.use_cases.create_task_use_case import CreateTaskUseCase
from components.project.application.use_cases.update_task_use_case import UpdateTaskUseCase


class ProjectProvider:

    @staticmethod
    def build_create_task_use_case() -> CreateTaskUseCase:
        from components.project.infrastructure.repositories.create_task_repository import (
            OrmCreateTaskRepository,
        )
        return CreateTaskUseCase(port=OrmCreateTaskRepository())

    @staticmethod
    def build_create_project_use_case() -> CreateProjectUseCase:
        from components.project.infrastructure.repositories.create_project_repository import (
            OrmCreateProjectRepository,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )
        return CreateProjectUseCase(
            port=OrmCreateProjectRepository(),
            event_publisher=CeleryEventPublisher(),
        )

    @staticmethod
    def build_update_task_use_case() -> UpdateTaskUseCase:
        from components.project.infrastructure.repositories.update_task_repository import (
            OrmUpdateTaskRepository,
        )
        return UpdateTaskUseCase(port=OrmUpdateTaskRepository())

    @staticmethod
    def build_batch_move_tasks_use_case() -> BatchMoveTasksUseCase:
        from components.project.infrastructure.repositories.batch_move_tasks_repository import (
            OrmBatchMoveTasksRepository,
        )
        return BatchMoveTasksUseCase(port=OrmBatchMoveTasksRepository())
