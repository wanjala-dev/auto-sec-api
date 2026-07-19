"""Unit tests for ProjectService application service.

Tests service orchestration, delegation to use cases, and behavior.
No Django dependencies, no database, pure unit tests.
"""

from unittest.mock import Mock, patch, MagicMock
from components.project.application.service import ProjectService
from components.project.application.ports.create_project_port import (
    CreateProjectCommand,
    CreateProjectResult,
)
from components.project.application.ports.create_task_port import (
    CreateTaskCommand,
    CreateTaskResult,
)
from components.project.application.ports.update_task_port import (
    UpdateTaskCommand,
    UpdateTaskResult,
)


class TestProjectServiceInitialization:
    """Test ProjectService initialization."""

    def test_project_service_can_be_instantiated(self):
        """ProjectService should be instantiable."""
        service = ProjectService()
        assert service is not None

    def test_project_service_has_project_provider(self):
        """ProjectService should have a project_provider field."""
        service = ProjectService()
        assert hasattr(service, "project_provider")
        assert service.project_provider is not None

    def test_project_service_default_factory_creates_provider(self):
        """ProjectService should use default factory for project_provider."""
        service1 = ProjectService()
        service2 = ProjectService()
        # Each instance should get its own provider instance
        assert service1.project_provider is not None
        assert service2.project_provider is not None

    def test_project_service_with_custom_provider(self):
        """ProjectService should accept custom provider."""
        mock_provider = Mock()
        service = ProjectService(project_provider=mock_provider)
        assert service.project_provider is mock_provider


class TestProjectServiceCreateProject:
    """Test ProjectService.create_project() orchestration."""

    def test_create_project_builds_use_case_from_provider(self):
        """create_project should use provider to build use case."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_provider.build_create_project_use_case.return_value = mock_use_case
        mock_use_case.execute.return_value = CreateProjectResult(success=True)

        service = ProjectService(project_provider=mock_provider)
        service.create_project(title="P", team_id="t", user_id="u")

        mock_provider.build_create_project_use_case.assert_called_once()

    def test_create_project_delegates_to_use_case(self):
        """create_project should build a command and delegate to execute()."""
        mock_provider = Mock()
        mock_use_case = Mock()
        expected_result = CreateProjectResult(success=True)
        mock_use_case.execute.return_value = expected_result
        mock_provider.build_create_project_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)
        result = service.create_project(
            title="Project", team_id="team-1", user_id="user-1"
        )

        assert result == expected_result
        mock_use_case.execute.assert_called_once_with(
            command=CreateProjectCommand(
                title="Project",
                team_id="team-1",
                user_id="user-1",
            )
        )

    def test_create_project_returns_use_case_result(self):
        """create_project should return use case result directly."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_provider.build_create_project_use_case.return_value = mock_use_case

        result1 = CreateProjectResult(success=True, project={"id": "1"})
        result2 = CreateProjectResult(success=False)

        service = ProjectService(project_provider=mock_provider)

        mock_use_case.execute.return_value = result1
        assert service.create_project(title="P", team_id="t", user_id="u") is result1

        mock_use_case.execute.return_value = result2
        assert service.create_project(title="P", team_id="t", user_id="u") is result2

    def test_create_project_passes_kwargs_to_use_case(self):
        """create_project should forward its kwargs onto the command."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_use_case.execute.return_value = CreateProjectResult()
        mock_provider.build_create_project_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)
        service.create_project(
            title="Project",
            team_id="team-1",
            user_id="user-1",
            workspace_id="ws-1",
        )

        mock_use_case.execute.assert_called_once_with(
            command=CreateProjectCommand(
                title="Project",
                team_id="team-1",
                user_id="user-1",
                workspace_id="ws-1",
            )
        )

    def test_create_project_with_complex_kwargs(self):
        """create_project should handle the full kwarg set, including the
        create_dedicated_budget flag, when building the command."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_use_case.execute.return_value = CreateProjectResult()
        mock_provider.build_create_project_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)
        service.create_project(
            title="Complex Project",
            team_id="team-123",
            user_id="user-456",
            workspace_id="ws-789",
            create_dedicated_budget=True,
        )

        mock_use_case.execute.assert_called_once_with(
            command=CreateProjectCommand(
                title="Complex Project",
                team_id="team-123",
                user_id="user-456",
                workspace_id="ws-789",
                create_dedicated_budget=True,
            )
        )


class TestProjectServiceCreateTask:
    """Test ProjectService.create_task() orchestration."""

    def test_create_task_builds_use_case_from_provider(self):
        """create_task should use provider to build use case."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_provider.build_create_task_use_case.return_value = mock_use_case
        mock_use_case.execute.return_value = CreateTaskResult()

        service = ProjectService(project_provider=mock_provider)
        service.create_task(
            command=CreateTaskCommand(
                title="Task",
                column_id="col-1",
                user_id="user-1",
            )
        )

        mock_provider.build_create_task_use_case.assert_called_once()

    def test_create_task_delegates_to_use_case(self):
        """create_task should delegate to use case.execute()."""
        mock_provider = Mock()
        mock_use_case = Mock()
        expected_result = CreateTaskResult(task_id="task-123")
        mock_use_case.execute.return_value = expected_result
        mock_provider.build_create_task_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)
        kwargs = {
            "command": CreateTaskCommand(
                title="Task",
                column_id="col-1",
                user_id="user-1",
            )
        }
        result = service.create_task(**kwargs)

        assert result == expected_result
        mock_use_case.execute.assert_called_once_with(**kwargs)

    def test_create_task_returns_use_case_result(self):
        """create_task should return use case result directly."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_provider.build_create_task_use_case.return_value = mock_use_case

        result1 = CreateTaskResult(task_id="task-1", status="open")
        result2 = CreateTaskResult(task_id="task-2", status="done")

        service = ProjectService(project_provider=mock_provider)
        cmd = CreateTaskCommand(
            title="Task",
            column_id="col-1",
            user_id="user-1",
        )

        mock_use_case.execute.return_value = result1
        assert service.create_task(command=cmd) is result1

        mock_use_case.execute.return_value = result2
        assert service.create_task(command=cmd) is result2

    def test_create_task_passes_kwargs_to_use_case(self):
        """create_task should pass all kwargs to use case.execute()."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_use_case.execute.return_value = CreateTaskResult()
        mock_provider.build_create_task_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)
        kwargs = {
            "command": CreateTaskCommand(
                title="Task",
                column_id="col-1",
                user_id="user-1",
                project_id="proj-1",
                workspace_id="ws-1",
            )
        }
        service.create_task(**kwargs)

        mock_use_case.execute.assert_called_once_with(**kwargs)


class TestProjectServiceUpdateTask:
    """Test ProjectService.update_task() orchestration."""

    def test_update_task_builds_use_case_from_provider(self):
        """update_task should use provider to build use case."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_provider.build_update_task_use_case.return_value = mock_use_case
        mock_use_case.execute.return_value = UpdateTaskResult(success=True)

        service = ProjectService(project_provider=mock_provider)
        service.update_task(
            command=UpdateTaskCommand(
                task_id="task-1",
                user_id="user-1",
            )
        )

        mock_provider.build_update_task_use_case.assert_called_once()

    def test_update_task_delegates_to_use_case(self):
        """update_task should delegate to use case.execute()."""
        mock_provider = Mock()
        mock_use_case = Mock()
        expected_result = UpdateTaskResult(success=True)
        mock_use_case.execute.return_value = expected_result
        mock_provider.build_update_task_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)
        kwargs = {
            "command": UpdateTaskCommand(
                task_id="task-1",
                user_id="user-1",
                data={"status": "done"},
            )
        }
        result = service.update_task(**kwargs)

        assert result == expected_result
        mock_use_case.execute.assert_called_once_with(**kwargs)

    def test_update_task_returns_use_case_result(self):
        """update_task should return use case result directly."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_provider.build_update_task_use_case.return_value = mock_use_case

        result1 = UpdateTaskResult(success=True, task={"id": "task-1"})
        result2 = UpdateTaskResult(success=False)

        service = ProjectService(project_provider=mock_provider)
        cmd = UpdateTaskCommand(
            task_id="task-1",
            user_id="user-1",
        )

        mock_use_case.execute.return_value = result1
        assert service.update_task(command=cmd) is result1

        mock_use_case.execute.return_value = result2
        assert service.update_task(command=cmd) is result2

    def test_update_task_passes_kwargs_to_use_case(self):
        """update_task should pass all kwargs to use case.execute()."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_use_case.execute.return_value = UpdateTaskResult()
        mock_provider.build_update_task_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)
        kwargs = {
            "command": UpdateTaskCommand(
                task_id="task-1",
                user_id="user-1",
                data={"title": "Updated", "status": "done"},
            )
        }
        service.update_task(**kwargs)

        mock_use_case.execute.assert_called_once_with(**kwargs)


class TestProjectServiceErrorPropagation:
    """Test that service propagates errors from use cases."""

    def test_service_propagates_use_case_exceptions(self):
        """Service should let use case exceptions propagate."""
        from components.project.domain.errors import ProjectNotFoundError

        mock_provider = Mock()
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = ProjectNotFoundError("Not found")
        mock_provider.build_create_project_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)

        try:
            service.create_project(title="P", team_id="t", user_id="u")
            assert False, "Should have raised ProjectNotFoundError"
        except ProjectNotFoundError as e:
            assert "Not found" in str(e)

    def test_service_propagates_task_validation_errors(self):
        """Service should propagate task validation errors."""
        from components.project.domain.errors import TaskValidationError

        mock_provider = Mock()
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = TaskValidationError("Invalid")
        mock_provider.build_create_task_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)
        cmd = CreateTaskCommand(
            title="Task",
            column_id="col-1",
            user_id="user-1",
        )

        try:
            service.create_task(command=cmd)
            assert False, "Should have raised TaskValidationError"
        except TaskValidationError as e:
            assert "Invalid" in str(e)


class TestProjectServiceOrchestration:
    """Test overall service orchestration patterns."""

    def test_service_creates_fresh_use_case_each_time(self):
        """Service should create fresh use case for each call."""
        mock_provider = Mock()
        mock_use_case1 = Mock()
        mock_use_case2 = Mock()
        mock_use_case1.execute.return_value = CreateProjectResult()
        mock_use_case2.execute.return_value = CreateProjectResult()
        mock_provider.build_create_project_use_case.side_effect = [
            mock_use_case1,
            mock_use_case2,
        ]

        service = ProjectService(project_provider=mock_provider)

        service.create_project(title="P", team_id="t", user_id="u")
        service.create_project(title="P", team_id="t", user_id="u")

        # Provider should be called twice
        assert mock_provider.build_create_project_use_case.call_count == 2

    def test_service_can_orchestrate_multiple_operations(self):
        """Service should support multiple operations in sequence."""
        mock_provider = Mock()

        # Setup different use cases
        create_proj_uc = Mock()
        create_proj_uc.execute.return_value = CreateProjectResult(
            success=True,
            project={"id": "proj-1"},
        )
        create_task_uc = Mock()
        create_task_uc.execute.return_value = CreateTaskResult(task_id="task-1")
        update_task_uc = Mock()
        update_task_uc.execute.return_value = UpdateTaskResult(success=True)

        mock_provider.build_create_project_use_case.return_value = create_proj_uc
        mock_provider.build_create_task_use_case.return_value = create_task_uc
        mock_provider.build_update_task_use_case.return_value = update_task_uc

        service = ProjectService(project_provider=mock_provider)

        proj_result = service.create_project(
            title="Project", team_id="team-1", user_id="user-1"
        )
        assert proj_result.project["id"] == "proj-1"

        task_result = service.create_task(
            command=CreateTaskCommand(
                title="Task",
                column_id="col-1",
                user_id="user-1",
            )
        )
        assert task_result.task_id == "task-1"

        update_result = service.update_task(
            command=UpdateTaskCommand(
                task_id="task-1",
                user_id="user-1",
            )
        )
        assert update_result.success is True

    def test_service_delegates_only_to_provider(self):
        """Service should delegate use case building only to provider."""
        mock_provider = Mock()
        mock_use_case = Mock()
        mock_use_case.execute.return_value = CreateProjectResult()
        mock_provider.build_create_project_use_case.return_value = mock_use_case

        service = ProjectService(project_provider=mock_provider)
        service.create_project(title="P", team_id="t", user_id="u")

        # Only provider method should be called
        mock_provider.build_create_project_use_case.assert_called_once()
        # No other provider methods should be called
        assert not mock_provider.build_create_task_use_case.called
        assert not mock_provider.build_update_task_use_case.called


class TestProjectServiceDataClassProperties:
    """Test ProjectService dataclass properties."""

    def test_project_service_is_dataclass(self):
        """ProjectService should be a dataclass."""
        from dataclasses import is_dataclass

        assert is_dataclass(ProjectService)

    def test_project_service_fields(self):
        """ProjectService should have expected fields."""
        from dataclasses import fields

        field_names = [f.name for f in fields(ProjectService)]
        assert "project_provider" in field_names

    def test_project_service_instances_are_independent(self):
        """ProjectService instances should be independent."""
        service1 = ProjectService()
        service2 = ProjectService()
        # Each should have separate provider
        assert service1.project_provider is not service2.project_provider
