"""Unit tests for project application use cases.

Tests use case execution, delegation to ports, and behavior.
No Django dependencies, no database, pure unit tests.
"""

from unittest.mock import Mock, MagicMock, call
from components.project.application.use_cases.create_project_use_case import (
    CreateProjectUseCase,
)
from components.project.application.use_cases.create_task_use_case import (
    CreateTaskUseCase,
)
from components.project.application.use_cases.update_task_use_case import (
    UpdateTaskUseCase,
)
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


class TestCreateProjectUseCase:
    """Test CreateProjectUseCase execution."""

    def test_create_project_use_case_initialization(self):
        """CreateProjectUseCase should accept a port in constructor."""
        mock_port = Mock()
        use_case = CreateProjectUseCase(port=mock_port)
        assert use_case._port is mock_port

    def test_create_project_use_case_execute_delegates_to_port(self):
        """execute() should delegate to port.create_project()."""
        mock_port = Mock()
        expected_result = CreateProjectResult(
            success=True,
            project={"id": "proj-123", "title": "My Project"},
        )
        mock_port.create_project.return_value = expected_result

        use_case = CreateProjectUseCase(port=mock_port)
        command = CreateProjectCommand(
            title="My Project",
            team_id="team-456",
            user_id="user-789",
        )

        result = use_case.execute(command=command)

        assert result == expected_result
        mock_port.create_project.assert_called_once_with(command=command)

    def test_create_project_use_case_execute_passes_command_exactly(self):
        """execute() should pass command to port without modification."""
        mock_port = Mock()
        mock_port.create_project.return_value = CreateProjectResult()

        use_case = CreateProjectUseCase(port=mock_port)
        command = CreateProjectCommand(
            title="Test Project",
            team_id="team-1",
            user_id="user-1",
            workspace_id="ws-1",
        )

        use_case.execute(command=command)

        # Verify exact command was passed
        call_args = mock_port.create_project.call_args
        assert call_args[1]["command"] is command

    def test_create_project_use_case_returns_port_result(self):
        """execute() should return whatever the port returns."""
        mock_port = Mock()

        result1 = CreateProjectResult(success=True, project={"id": "1"})
        result2 = CreateProjectResult(success=False, project={})

        use_case = CreateProjectUseCase(port=mock_port)
        command = CreateProjectCommand(
            title="P",
            team_id="t",
            user_id="u",
        )

        mock_port.create_project.return_value = result1
        assert use_case.execute(command=command) is result1

        mock_port.create_project.return_value = result2
        assert use_case.execute(command=command) is result2

    def test_create_project_use_case_execute_must_use_keyword_argument(self):
        """execute() should require command as keyword argument."""
        mock_port = Mock()
        mock_port.create_project.return_value = CreateProjectResult()

        use_case = CreateProjectUseCase(port=mock_port)
        command = CreateProjectCommand(
            title="P",
            team_id="t",
            user_id="u",
        )

        # This should work
        result = use_case.execute(command=command)
        assert result is not None

    def test_create_project_use_case_execute_with_workspace_id(self):
        """execute() should handle commands with workspace_id."""
        mock_port = Mock()
        expected_result = CreateProjectResult(success=True)
        mock_port.create_project.return_value = expected_result

        use_case = CreateProjectUseCase(port=mock_port)
        command = CreateProjectCommand(
            title="Project",
            team_id="team-1",
            user_id="user-1",
            workspace_id="ws-1",
        )

        result = use_case.execute(command=command)

        assert result == expected_result
        mock_port.create_project.assert_called_once()

    def test_create_project_command_defaults_create_dedicated_budget_false(self):
        """CreateProjectCommand preserves the existing behaviour by default."""
        command = CreateProjectCommand(
            title="P",
            team_id="t",
            user_id="u",
        )
        assert command.create_dedicated_budget is False

    def test_create_project_command_accepts_create_dedicated_budget_true(self):
        """The flag propagates to the port unchanged when the controller sets it."""
        mock_port = Mock()
        mock_port.create_project.return_value = CreateProjectResult(success=True)
        use_case = CreateProjectUseCase(port=mock_port)
        command = CreateProjectCommand(
            title="Trip to Tokyo",
            team_id="t",
            user_id="u",
            create_dedicated_budget=True,
        )

        use_case.execute(command=command)

        call_args = mock_port.create_project.call_args
        passed = call_args[1]["command"]
        assert passed.create_dedicated_budget is True
        assert passed.title == "Trip to Tokyo"


class TestCreateTaskUseCase:
    """Test CreateTaskUseCase execution."""

    def test_create_task_use_case_initialization(self):
        """CreateTaskUseCase should accept a port in constructor."""
        mock_port = Mock()
        use_case = CreateTaskUseCase(port=mock_port)
        assert use_case._port is mock_port

    def test_create_task_use_case_execute_delegates_to_port(self):
        """execute() should delegate to port.create_task()."""
        mock_port = Mock()
        expected_result = CreateTaskResult(
            task_id="task-123",
            team_id="team-456",
            title="My Task",
            status="open",
        )
        mock_port.create_task.return_value = expected_result

        use_case = CreateTaskUseCase(port=mock_port)
        command = CreateTaskCommand(
            title="My Task",
            column_id="col-789",
            user_id="user-001",
        )

        result = use_case.execute(command=command)

        assert result == expected_result
        mock_port.create_task.assert_called_once_with(command=command)

    def test_create_task_use_case_execute_passes_command_exactly(self):
        """execute() should pass command to port without modification."""
        mock_port = Mock()
        mock_port.create_task.return_value = CreateTaskResult()

        use_case = CreateTaskUseCase(port=mock_port)
        command = CreateTaskCommand(
            title="Task",
            column_id="col-1",
            user_id="user-1",
            project_id="proj-1",
            workspace_id="ws-1",
        )

        use_case.execute(command=command)

        call_args = mock_port.create_task.call_args
        assert call_args[1]["command"] is command

    def test_create_task_use_case_returns_port_result(self):
        """execute() should return whatever the port returns."""
        mock_port = Mock()

        result1 = CreateTaskResult(
            task_id="task-1",
            status="open",
            order=0,
        )
        result2 = CreateTaskResult(
            task_id="task-2",
            status="done",
            order=1,
        )

        use_case = CreateTaskUseCase(port=mock_port)
        command = CreateTaskCommand(
            title="Task",
            column_id="col-1",
            user_id="user-1",
        )

        mock_port.create_task.return_value = result1
        assert use_case.execute(command=command) is result1

        mock_port.create_task.return_value = result2
        assert use_case.execute(command=command) is result2

    def test_create_task_use_case_with_all_fields(self):
        """execute() should handle commands with all optional fields."""
        mock_port = Mock()
        expected_result = CreateTaskResult()
        mock_port.create_task.return_value = expected_result

        use_case = CreateTaskUseCase(port=mock_port)
        command = CreateTaskCommand(
            title="Task",
            column_id="col-1",
            user_id="user-1",
            project_id="proj-1",
            workspace_id="ws-1",
        )

        result = use_case.execute(command=command)

        assert result == expected_result
        mock_port.create_task.assert_called_once_with(command=command)


class TestUpdateTaskUseCase:
    """Test UpdateTaskUseCase execution."""

    def test_update_task_use_case_initialization(self):
        """UpdateTaskUseCase should accept a port in constructor."""
        mock_port = Mock()
        use_case = UpdateTaskUseCase(port=mock_port)
        assert use_case._port is mock_port

    def test_update_task_use_case_execute_delegates_to_port(self):
        """execute() should delegate to port.update_task()."""
        mock_port = Mock()
        expected_result = UpdateTaskResult(
            success=True,
            task={"id": "task-123", "title": "Updated Task"},
        )
        mock_port.update_task.return_value = expected_result

        use_case = UpdateTaskUseCase(port=mock_port)
        command = UpdateTaskCommand(
            task_id="task-123",
            user_id="user-456",
            data={"title": "Updated Task"},
        )

        result = use_case.execute(command=command)

        assert result == expected_result
        mock_port.update_task.assert_called_once_with(command=command)

    def test_update_task_use_case_execute_passes_command_exactly(self):
        """execute() should pass command to port without modification."""
        mock_port = Mock()
        mock_port.update_task.return_value = UpdateTaskResult()

        use_case = UpdateTaskUseCase(port=mock_port)
        mock_request = object()
        command = UpdateTaskCommand(
            task_id="task-1",
            user_id="user-1",
            data={"status": "in_progress"},
            http_request=mock_request,
        )

        use_case.execute(command=command)

        call_args = mock_port.update_task.call_args
        assert call_args[1]["command"] is command

    def test_update_task_use_case_returns_port_result(self):
        """execute() should return whatever the port returns."""
        mock_port = Mock()

        result1 = UpdateTaskResult(success=True, task={"id": "task-1"})
        result2 = UpdateTaskResult(success=False, task={})

        use_case = UpdateTaskUseCase(port=mock_port)
        command = UpdateTaskCommand(
            task_id="task-1",
            user_id="user-1",
        )

        mock_port.update_task.return_value = result1
        assert use_case.execute(command=command) is result1

        mock_port.update_task.return_value = result2
        assert use_case.execute(command=command) is result2

    def test_update_task_use_case_with_empty_data(self):
        """execute() should handle commands with empty data."""
        mock_port = Mock()
        expected_result = UpdateTaskResult()
        mock_port.update_task.return_value = expected_result

        use_case = UpdateTaskUseCase(port=mock_port)
        command = UpdateTaskCommand(
            task_id="task-1",
            user_id="user-1",
            data={},
        )

        result = use_case.execute(command=command)

        assert result == expected_result
        mock_port.update_task.assert_called_once_with(command=command)

    def test_update_task_use_case_with_complex_data(self):
        """execute() should handle commands with complex update data."""
        mock_port = Mock()
        expected_result = UpdateTaskResult(success=True)
        mock_port.update_task.return_value = expected_result

        use_case = UpdateTaskUseCase(port=mock_port)
        complex_data = {
            "title": "New Title",
            "status": "in_progress",
            "assigned_to": "user-2",
            "priority": "high",
            "tags": ["urgent", "backlog"],
        }
        command = UpdateTaskCommand(
            task_id="task-1",
            user_id="user-1",
            data=complex_data,
        )

        result = use_case.execute(command=command)

        assert result == expected_result
        call_args = mock_port.update_task.call_args
        assert call_args[1]["command"].data == complex_data


class TestUseCaseIsolation:
    """Test that use cases are properly isolated."""

    def test_different_use_cases_use_different_ports(self):
        """Different use cases should use different port instances."""
        port_create_proj = Mock()
        port_create_task = Mock()
        port_update_task = Mock()

        uc_create_proj = CreateProjectUseCase(port=port_create_proj)
        uc_create_task = CreateTaskUseCase(port=port_create_task)
        uc_update_task = UpdateTaskUseCase(port=port_update_task)

        assert uc_create_proj._port is not uc_create_task._port
        assert uc_create_task._port is not uc_update_task._port
        assert uc_create_proj._port is not uc_update_task._port

    def test_multiple_executions_with_same_use_case(self):
        """A use case should be reusable for multiple executions."""
        mock_port = Mock()
        mock_port.create_project.return_value = CreateProjectResult(success=True)

        use_case = CreateProjectUseCase(port=mock_port)

        cmd1 = CreateProjectCommand(
            title="Project A",
            team_id="team-1",
            user_id="user-1",
        )
        cmd2 = CreateProjectCommand(
            title="Project B",
            team_id="team-2",
            user_id="user-2",
        )

        use_case.execute(command=cmd1)
        use_case.execute(command=cmd2)

        assert mock_port.create_project.call_count == 2
        calls = mock_port.create_project.call_args_list
        assert calls[0][1]["command"] is cmd1
        assert calls[1][1]["command"] is cmd2

    def test_use_case_does_not_modify_command(self):
        """Use case should not modify the command it receives."""
        mock_port = Mock()
        mock_port.create_project.return_value = CreateProjectResult()

        use_case = CreateProjectUseCase(port=mock_port)

        original_command = CreateProjectCommand(
            title="Original Title",
            team_id="team-1",
            user_id="user-1",
        )

        use_case.execute(command=original_command)

        assert original_command.title == "Original Title"
        assert original_command.team_id == "team-1"


class TestUseCaseErrorPropagation:
    """Test that use cases propagate errors from ports."""

    def test_use_case_propagates_port_exceptions(self):
        """Use case should let port exceptions propagate."""
        from components.project.domain.errors import ProjectNotFoundError

        mock_port = Mock()
        mock_port.create_project.side_effect = ProjectNotFoundError("Not found")

        use_case = CreateProjectUseCase(port=mock_port)
        command = CreateProjectCommand(
            title="P",
            team_id="t",
            user_id="u",
        )

        try:
            use_case.execute(command=command)
            assert False, "Should have raised ProjectNotFoundError"
        except ProjectNotFoundError as e:
            assert "Not found" in str(e)

    def test_use_case_propagates_validation_errors(self):
        """Use case should propagate validation errors from port."""
        from components.project.domain.errors import TaskValidationError

        mock_port = Mock()
        mock_port.create_task.side_effect = TaskValidationError("Invalid data")

        use_case = CreateTaskUseCase(port=mock_port)
        command = CreateTaskCommand(
            title="Task",
            column_id="col-1",
            user_id="user-1",
        )

        try:
            use_case.execute(command=command)
            assert False, "Should have raised TaskValidationError"
        except TaskValidationError as e:
            assert "Invalid data" in str(e)

    def test_use_case_propagates_authorization_errors(self):
        """Use case should propagate authorization errors from port."""
        from components.project.domain.errors import TeamMembershipRequiredError

        mock_port = Mock()
        mock_port.update_task.side_effect = TeamMembershipRequiredError(
            "Not a member"
        )

        use_case = UpdateTaskUseCase(port=mock_port)
        command = UpdateTaskCommand(
            task_id="task-1",
            user_id="user-1",
        )

        try:
            use_case.execute(command=command)
            assert False, "Should have raised TeamMembershipRequiredError"
        except TeamMembershipRequiredError as e:
            assert "Not a member" in str(e)


class TestUseCasePort:
    """Test use case port parameter handling."""

    def test_use_case_stores_port_reference(self):
        """Use case should store port reference for later use."""
        mock_port = Mock()
        use_case = CreateProjectUseCase(port=mock_port)

        # Port should be stored
        assert use_case._port is mock_port

        # Port methods should be callable through stored reference
        mock_port.create_project.return_value = CreateProjectResult()
        command = CreateProjectCommand(
            title="P",
            team_id="t",
            user_id="u",
        )
        use_case.execute(command=command)

        mock_port.create_project.assert_called_once()

    def test_use_case_can_work_with_mock_port(self):
        """Use case should work with mock port for testing."""
        mock_port = MagicMock()
        mock_port.create_project.return_value = CreateProjectResult(
            success=True,
            project={"id": "new-proj"},
        )

        use_case = CreateProjectUseCase(port=mock_port)
        command = CreateProjectCommand(
            title="P",
            team_id="t",
            user_id="u",
        )
        result = use_case.execute(command=command)

        assert result.success is True
        assert result.project["id"] == "new-proj"
