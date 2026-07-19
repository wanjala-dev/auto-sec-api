"""Unit tests for project port command and result dataclasses.

Tests port definitions including commands, results, and their properties.
"""

from dataclasses import astuple, fields
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


class TestCreateProjectCommand:
    """Test CreateProjectCommand dataclass."""

    def test_create_project_command_required_fields(self):
        """CreateProjectCommand requires title, team_id, and user_id."""
        command = CreateProjectCommand(
            title="My Project",
            team_id="team-123",
            user_id="user-456",
        )
        assert command.title == "My Project"
        assert command.team_id == "team-123"
        assert command.user_id == "user-456"
        assert command.workspace_id is None

    def test_create_project_command_with_workspace_id(self):
        """CreateProjectCommand should accept optional workspace_id."""
        command = CreateProjectCommand(
            title="My Project",
            team_id="team-123",
            user_id="user-456",
            workspace_id="workspace-789",
        )
        assert command.workspace_id == "workspace-789"

    def test_create_project_command_is_frozen(self):
        """CreateProjectCommand should be immutable (frozen)."""
        command = CreateProjectCommand(
            title="My Project",
            team_id="team-123",
            user_id="user-456",
        )
        try:
            command.title = "Different Title"
            assert False, "Should not be able to modify frozen dataclass"
        except AttributeError:
            pass  # Expected

    def test_create_project_command_equality(self):
        """CreateProjectCommand instances should support equality comparison."""
        cmd1 = CreateProjectCommand(
            title="Project A",
            team_id="team-1",
            user_id="user-1",
        )
        cmd2 = CreateProjectCommand(
            title="Project A",
            team_id="team-1",
            user_id="user-1",
        )
        cmd3 = CreateProjectCommand(
            title="Project B",
            team_id="team-1",
            user_id="user-1",
        )
        assert cmd1 == cmd2
        assert cmd1 != cmd3

    def test_create_project_command_with_special_characters(self):
        """CreateProjectCommand should handle special characters in strings."""
        command = CreateProjectCommand(
            title="Project: Q&A [Archive]",
            team_id="team-123_abc",
            user_id="user-456.def",
            workspace_id="ws/789",
        )
        assert command.title == "Project: Q&A [Archive]"

    def test_create_project_command_field_names(self):
        """Verify CreateProjectCommand has expected fields."""
        command = CreateProjectCommand(
            title="P",
            team_id="t",
            user_id="u",
        )
        field_names = [f.name for f in fields(command)]
        assert "title" in field_names
        assert "team_id" in field_names
        assert "user_id" in field_names
        assert "workspace_id" in field_names
        assert "create_dedicated_budget" in field_names
        assert len(field_names) == 5


class TestCreateProjectResult:
    """Test CreateProjectResult dataclass."""

    def test_create_project_result_defaults(self):
        """CreateProjectResult should have sensible defaults."""
        result = CreateProjectResult()
        assert result.success is True
        # project defaults to None (no project payload until one is built).
        assert result.project is None

    def test_create_project_result_with_data(self):
        """CreateProjectResult should accept success flag and project data."""
        project_data = {
            "id": "proj-123",
            "title": "My Project",
            "team_id": "team-456",
        }
        result = CreateProjectResult(success=True, project=project_data)
        assert result.success is True
        assert result.project == project_data
        assert result.project["id"] == "proj-123"

    def test_create_project_result_failure(self):
        """CreateProjectResult should support failure state."""
        result = CreateProjectResult(success=False, project={})
        assert result.success is False
        assert result.project == {}

    def test_create_project_result_with_complex_project_data(self):
        """CreateProjectResult should handle complex nested project data."""
        project_data = {
            "id": "proj-123",
            "title": "Project A",
            "team": {
                "id": "team-456",
                "name": "Team A",
            },
            "columns": [
                {"id": "col-1", "name": "Todo"},
                {"id": "col-2", "name": "In Progress"},
            ],
            "metadata": {
                "created_at": "2026-04-02T10:00:00Z",
                "updated_at": "2026-04-02T10:00:00Z",
            },
        }
        result = CreateProjectResult(success=True, project=project_data)
        assert result.project["id"] == "proj-123"
        assert result.project["team"]["name"] == "Team A"
        assert len(result.project["columns"]) == 2

    def test_create_project_result_is_mutable(self):
        """CreateProjectResult should be mutable (not frozen)."""
        result = CreateProjectResult()
        result.success = False
        assert result.success is False
        result.project = {"id": "new-proj"}
        assert result.project["id"] == "new-proj"

    def test_create_project_result_field_names(self):
        """Verify CreateProjectResult has expected fields."""
        result = CreateProjectResult()
        field_names = [f.name for f in fields(result)]
        assert "success" in field_names
        assert "project" in field_names
        assert len(field_names) == 2


class TestCreateTaskCommand:
    """Test CreateTaskCommand dataclass."""

    def test_create_task_command_required_fields(self):
        """CreateTaskCommand requires title, column_id, and user_id."""
        command = CreateTaskCommand(
            title="Task Title",
            column_id="col-123",
            user_id="user-456",
        )
        assert command.title == "Task Title"
        assert command.column_id == "col-123"
        assert command.user_id == "user-456"
        assert command.project_id is None
        assert command.workspace_id is None
        # Phase 4-prep: source_type defaults to None (human-created task)
        assert command.source_type is None

    def test_create_task_command_carries_source_type(self):
        """source_type lets the workflow trigger route AI-finding tasks
        without joining through AIAction (Phase 4-prep)."""
        command = CreateTaskCommand(
            title="t",
            column_id="c",
            user_id="u",
            source_type="ai.book_balance.budget_overrun",
        )
        assert command.source_type == "ai.book_balance.budget_overrun"

    def test_create_task_command_with_all_fields(self):
        """CreateTaskCommand should accept optional project_id and workspace_id."""
        command = CreateTaskCommand(
            title="Task Title",
            column_id="col-123",
            user_id="user-456",
            project_id="proj-789",
            workspace_id="ws-012",
        )
        assert command.project_id == "proj-789"
        assert command.workspace_id == "ws-012"

    def test_create_task_command_is_frozen(self):
        """CreateTaskCommand should be immutable (frozen)."""
        command = CreateTaskCommand(
            title="Task",
            column_id="col-1",
            user_id="user-1",
        )
        try:
            command.title = "Different"
            assert False, "Should not be able to modify frozen dataclass"
        except AttributeError:
            pass  # Expected

    def test_create_task_command_equality(self):
        """CreateTaskCommand instances should support equality comparison."""
        cmd1 = CreateTaskCommand(
            title="Task A",
            column_id="col-1",
            user_id="user-1",
        )
        cmd2 = CreateTaskCommand(
            title="Task A",
            column_id="col-1",
            user_id="user-1",
        )
        cmd3 = CreateTaskCommand(
            title="Task B",
            column_id="col-1",
            user_id="user-1",
        )
        assert cmd1 == cmd2
        assert cmd1 != cmd3

    def test_create_task_command_field_names(self):
        """Verify CreateTaskCommand has expected fields."""
        command = CreateTaskCommand(
            title="T",
            column_id="c",
            user_id="u",
        )
        field_names = [f.name for f in fields(command)]
        assert "title" in field_names
        assert "column_id" in field_names
        assert "user_id" in field_names
        assert "project_id" in field_names
        assert "event_id" in field_names
        assert "campaign_id" in field_names
        assert "recipient_id" in field_names
        assert "grant_id" in field_names
        assert "workspace_id" in field_names
        assert "source_type" in field_names
        # Phase 4-prep additions: free-form narrative + structured payload
        # that replaced the retired AIAction.summary / .payload fields.
        assert "description" in field_names
        assert "metadata" in field_names
        # Phase 6b addition: optional owner assignment for sign-off tasks.
        assert "assigned_to_ids" in field_names
        # Task-creation-wizard additions: planning fields captured at
        # creation instead of post-creation PATCH.
        assert "due_date" in field_names
        assert "priority" in field_names
        assert len(field_names) == 15


class TestCreateTaskResult:
    """Test CreateTaskResult dataclass."""

    def test_create_task_result_defaults(self):
        """CreateTaskResult should have default empty values."""
        result = CreateTaskResult()
        assert result.task_id == ""
        assert result.team_id == ""
        assert result.workspace_id == ""
        assert result.created_by == ""
        assert result.updated_at == ""
        assert result.title == ""
        assert result.created_at == ""
        assert result.project_id is None
        assert result.event_id is None
        assert result.campaign_id is None
        assert result.recipient_id is None
        assert result.grant_id is None
        assert result.status == ""
        assert result.column_id == ""
        assert result.order == 0

    def test_create_task_result_with_data(self):
        """CreateTaskResult should accept task data."""
        result = CreateTaskResult(
            task_id="task-123",
            team_id="team-456",
            workspace_id="ws-789",
            created_by="user-001",
            updated_at="2026-04-02T10:00:00Z",
            title="My Task",
            created_at="2026-04-02T09:00:00Z",
            project_id="proj-111",
            status="open",
            column_id="col-222",
            order=1,
        )
        assert result.task_id == "task-123"
        assert result.team_id == "team-456"
        assert result.workspace_id == "ws-789"
        assert result.created_by == "user-001"
        assert result.status == "open"
        assert result.order == 1

    def test_create_task_result_is_mutable(self):
        """CreateTaskResult should be mutable."""
        result = CreateTaskResult()
        result.task_id = "new-task"
        assert result.task_id == "new-task"

    def test_create_task_result_field_count(self):
        """Verify CreateTaskResult has expected field count."""
        result = CreateTaskResult()
        field_count = len(fields(result))
        # 15 originals + description / due_date / priority / assigned_to_ids
        # (task-creation-wizard planning fields echoed back to the caller).
        assert field_count == 19

    def test_create_task_result_with_partial_data(self):
        """CreateTaskResult should allow partial data initialization."""
        result = CreateTaskResult(
            task_id="task-1",
            team_id="team-1",
        )
        assert result.task_id == "task-1"
        assert result.team_id == "team-1"
        assert result.workspace_id == ""


class TestUpdateTaskCommand:
    """Test UpdateTaskCommand dataclass."""

    def test_update_task_command_required_fields(self):
        """UpdateTaskCommand requires task_id and user_id."""
        command = UpdateTaskCommand(
            task_id="task-123",
            user_id="user-456",
        )
        assert command.task_id == "task-123"
        assert command.user_id == "user-456"
        assert command.data == {}
        assert command.http_request is None

    def test_update_task_command_with_data(self):
        """UpdateTaskCommand should accept update data."""
        update_data = {
            "title": "Updated Title",
            "status": "in_progress",
            "assigned_to": "user-789",
        }
        command = UpdateTaskCommand(
            task_id="task-123",
            user_id="user-456",
            data=update_data,
        )
        assert command.data == update_data
        assert command.data["title"] == "Updated Title"

    def test_update_task_command_with_http_request(self):
        """UpdateTaskCommand should accept http_request context."""
        mock_request = object()  # Any object for testing
        command = UpdateTaskCommand(
            task_id="task-123",
            user_id="user-456",
            http_request=mock_request,
        )
        assert command.http_request is mock_request

    def test_update_task_command_is_frozen(self):
        """UpdateTaskCommand should be immutable (frozen)."""
        command = UpdateTaskCommand(
            task_id="task-1",
            user_id="user-1",
        )
        try:
            command.task_id = "task-2"
            assert False, "Should not be able to modify frozen dataclass"
        except AttributeError:
            pass  # Expected

    def test_update_task_command_equality(self):
        """UpdateTaskCommand instances should support equality comparison."""
        cmd1 = UpdateTaskCommand(
            task_id="task-1",
            user_id="user-1",
            data={"status": "done"},
        )
        cmd2 = UpdateTaskCommand(
            task_id="task-1",
            user_id="user-1",
            data={"status": "done"},
        )
        cmd3 = UpdateTaskCommand(
            task_id="task-2",
            user_id="user-1",
            data={"status": "done"},
        )
        assert cmd1 == cmd2
        assert cmd1 != cmd3

    def test_update_task_command_with_empty_data(self):
        """UpdateTaskCommand should handle empty data dict."""
        command = UpdateTaskCommand(
            task_id="task-123",
            user_id="user-456",
            data={},
        )
        assert command.data == {}

    def test_update_task_command_field_names(self):
        """Verify UpdateTaskCommand has expected fields."""
        command = UpdateTaskCommand(
            task_id="t",
            user_id="u",
        )
        field_names = [f.name for f in fields(command)]
        assert "task_id" in field_names
        assert "user_id" in field_names
        assert "data" in field_names
        assert "http_request" in field_names
        assert len(field_names) == 4


class TestUpdateTaskResult:
    """Test UpdateTaskResult dataclass."""

    def test_update_task_result_defaults(self):
        """UpdateTaskResult should have sensible defaults."""
        result = UpdateTaskResult()
        assert result.success is True
        assert result.task == {}

    def test_update_task_result_with_data(self):
        """UpdateTaskResult should accept success flag and task data."""
        task_data = {
            "id": "task-123",
            "title": "Updated Task",
            "status": "in_progress",
        }
        result = UpdateTaskResult(success=True, task=task_data)
        assert result.success is True
        assert result.task == task_data
        assert result.task["id"] == "task-123"

    def test_update_task_result_failure(self):
        """UpdateTaskResult should support failure state."""
        result = UpdateTaskResult(success=False)
        assert result.success is False
        assert result.task == {}

    def test_update_task_result_is_mutable(self):
        """UpdateTaskResult should be mutable."""
        result = UpdateTaskResult()
        result.success = False
        assert result.success is False

    def test_update_task_result_with_complex_task_data(self):
        """UpdateTaskResult should handle complex nested task data."""
        task_data = {
            "id": "task-123",
            "title": "Updated Task",
            "status": "in_progress",
            "assigned_to": {
                "id": "user-1",
                "name": "John Doe",
                "email": "john@example.com",
            },
            "timeline": {
                "created_at": "2026-04-01T10:00:00Z",
                "updated_at": "2026-04-02T11:00:00Z",
            },
            "comments": [
                {"id": "comment-1", "text": "Starting work"},
                {"id": "comment-2", "text": "Almost done"},
            ],
        }
        result = UpdateTaskResult(success=True, task=task_data)
        assert result.task["assigned_to"]["name"] == "John Doe"
        assert len(result.task["comments"]) == 2

    def test_update_task_result_field_names(self):
        """Verify UpdateTaskResult has expected fields."""
        result = UpdateTaskResult()
        field_names = [f.name for f in fields(result)]
        assert "success" in field_names
        assert "task" in field_names
        assert len(field_names) == 2


class TestPortDataclassInteroperability:
    """Test interactions between port dataclasses."""

    def test_commands_and_results_are_distinct(self):
        """Commands and results should be distinct types."""
        cmd = CreateProjectCommand(
            title="P",
            team_id="t",
            user_id="u",
        )
        result = CreateProjectResult()
        assert type(cmd) != type(result)
        assert not isinstance(cmd, CreateProjectResult)
        assert not isinstance(result, CreateProjectCommand)

    def test_multiple_commands_can_coexist(self):
        """Different command types should coexist without conflicts."""
        create_proj_cmd = CreateProjectCommand(
            title="Project",
            team_id="t",
            user_id="u",
        )
        create_task_cmd = CreateTaskCommand(
            title="Task",
            column_id="c",
            user_id="u",
        )
        update_task_cmd = UpdateTaskCommand(
            task_id="t",
            user_id="u",
        )
        assert create_proj_cmd.title == "Project"
        assert create_task_cmd.title == "Task"
        assert update_task_cmd.task_id == "t"

    def test_results_can_be_serialized_to_dict(self):
        """Results should be convertible to dictionaries."""
        result = CreateProjectResult(
            success=True,
            project={"id": "proj-1", "title": "Project A"},
        )
        # Manually construct dict representation
        result_dict = {
            "success": result.success,
            "project": result.project,
        }
        assert result_dict["success"] is True
        assert result_dict["project"]["id"] == "proj-1"
