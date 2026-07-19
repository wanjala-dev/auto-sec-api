"""Application service for the project bounded context.

Orchestration only – delegates to use cases for business logic.
This is the single orchestration entry point for the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.project.application.providers.project_provider import ProjectProvider


@dataclass
class ProjectService:
    """Application service for the project bounded context.

    Orchestration only – delegates to use cases for business logic.
    """

    project_provider: ProjectProvider = field(default_factory=ProjectProvider)

    def create_project(self, **kwargs):
        """Orchestrate project creation.

        Delegates to CreateProjectUseCase.
        """
        from components.project.application.ports.create_project_port import (
            CreateProjectCommand,
        )

        use_case = self.project_provider.build_create_project_use_case()
        command = CreateProjectCommand(
            title=kwargs["title"],
            team_id=kwargs["team_id"],
            user_id=kwargs["user_id"],
            workspace_id=kwargs.get("workspace_id"),
            create_dedicated_budget=bool(kwargs.get("create_dedicated_budget", False)),
        )
        return use_case.execute(command=command)

    def create_task(self, *, command):
        """Orchestrate task creation.

        Delegates to CreateTaskUseCase.
        """
        use_case = self.project_provider.build_create_task_use_case()
        return use_case.execute(command=command)

    def update_task(self, *, command):
        """Orchestrate task update.

        Delegates to UpdateTaskUseCase.
        """
        use_case = self.project_provider.build_update_task_use_case()
        return use_case.execute(command=command)

    def batch_move_tasks(self, *, command):
        """Orchestrate batch task moves.

        Delegates to BatchMoveTasksUseCase.
        """
        use_case = self.project_provider.build_batch_move_tasks_use_case()
        return use_case.execute(command=command)
