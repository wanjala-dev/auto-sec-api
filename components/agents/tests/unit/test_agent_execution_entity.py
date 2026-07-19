"""Unit tests for AgentExecutionEntity."""

from datetime import datetime
from uuid import uuid4

from components.agents.domain.entities.agent_execution_entity import (
    AgentExecutionEntity,
)


class TestAgentExecutionEntity:
    """Tests for AgentExecutionEntity — execution records for agents."""

    def test_create_minimal_execution(self):
        """Test creating an execution with minimal required fields."""
        exec_id = 1
        agent_id = uuid4()
        query = "What is the current budget status?"

        execution = AgentExecutionEntity(
            id=exec_id,
            agent_id=agent_id,
            query=query,
            status="pending",
        )

        assert execution.id == exec_id
        assert execution.agent_id == agent_id
        assert execution.query == query
        assert execution.status == "pending"
        assert execution.success is True
        assert execution.result == ""
        assert execution.error_message == ""
        assert execution.execution_time_ms is None
        assert execution.task_id == ""
        assert execution.progress == 0
        assert execution.state == {}
        assert execution.triggered_by_id is None
        assert execution.created_at is None
        assert execution.updated_at is None

    def test_create_execution_with_all_fields(self):
        """Test creating an execution with all fields populated."""
        exec_id = 42
        agent_id = uuid4()
        triggered_by_id = uuid4()
        now = datetime.utcnow()
        state = {"step": "analyzing", "details": "gathering data"}

        execution = AgentExecutionEntity(
            id=exec_id,
            agent_id=agent_id,
            query="Analyze recent spending trends",
            status="completed",
            success=True,
            result="Spending is up 15% YoY in utilities",
            error_message="",
            execution_time_ms=2500,
            task_id="task_xyz_123",
            progress=100,
            state=state,
            triggered_by_id=triggered_by_id,
            created_at=now,
            updated_at=now,
        )

        assert execution.id == exec_id
        assert execution.agent_id == agent_id
        assert execution.query == "Analyze recent spending trends"
        assert execution.status == "completed"
        assert execution.success is True
        assert execution.result == "Spending is up 15% YoY in utilities"
        assert execution.error_message == ""
        assert execution.execution_time_ms == 2500
        assert execution.task_id == "task_xyz_123"
        assert execution.progress == 100
        assert execution.state == state
        assert execution.triggered_by_id == triggered_by_id
        assert execution.created_at == now
        assert execution.updated_at == now

    def test_execution_is_frozen(self):
        """Test that AgentExecutionEntity is immutable."""
        execution = AgentExecutionEntity(
            id=1,
            agent_id=uuid4(),
            query="Test",
            status="pending",
        )

        try:
            execution.progress = 50
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected

    def test_execution_status_transitions(self):
        """Test creating executions with different status values."""
        agent_id = uuid4()

        pending = AgentExecutionEntity(
            id=1, agent_id=agent_id, query="q", status="pending"
        )
        running = AgentExecutionEntity(
            id=2, agent_id=agent_id, query="q", status="running"
        )
        completed = AgentExecutionEntity(
            id=3, agent_id=agent_id, query="q", status="completed"
        )
        failed = AgentExecutionEntity(
            id=4, agent_id=agent_id, query="q", status="failed"
        )

        assert pending.status == "pending"
        assert running.status == "running"
        assert completed.status == "completed"
        assert failed.status == "failed"

    def test_successful_execution_without_error(self):
        """Test a successful execution has no error message."""
        execution = AgentExecutionEntity(
            id=1,
            agent_id=uuid4(),
            query="List all budgets",
            status="completed",
            success=True,
            result="[budget1, budget2, budget3]",
            error_message="",
        )

        assert execution.success is True
        assert execution.error_message == ""
        assert execution.result == "[budget1, budget2, budget3]"

    def test_failed_execution_with_error(self):
        """Test a failed execution includes error message."""
        execution = AgentExecutionEntity(
            id=1,
            agent_id=uuid4(),
            query="Create new budget",
            status="failed",
            success=False,
            result="",
            error_message="Database connection timeout",
        )

        assert execution.success is False
        assert execution.error_message == "Database connection timeout"
        assert execution.result == ""

    def test_execution_progress_tracking(self):
        """Test progress field from 0 to 100."""
        agent_id = uuid4()

        exec_0 = AgentExecutionEntity(
            id=1, agent_id=agent_id, query="q", status="pending", progress=0
        )
        exec_50 = AgentExecutionEntity(
            id=2, agent_id=agent_id, query="q", status="running", progress=50
        )
        exec_100 = AgentExecutionEntity(
            id=3, agent_id=agent_id, query="q", status="completed", progress=100
        )

        assert exec_0.progress == 0
        assert exec_50.progress == 50
        assert exec_100.progress == 100

    def test_execution_time_metrics(self):
        """Test execution time tracking."""
        agent_id = uuid4()

        fast_exec = AgentExecutionEntity(
            id=1,
            agent_id=agent_id,
            query="q",
            status="completed",
            execution_time_ms=50,
        )

        normal_exec = AgentExecutionEntity(
            id=2,
            agent_id=agent_id,
            query="q",
            status="completed",
            execution_time_ms=500,
        )

        slow_exec = AgentExecutionEntity(
            id=3,
            agent_id=agent_id,
            query="q",
            status="completed",
            execution_time_ms=5000,
        )

        assert fast_exec.execution_time_ms == 50
        assert normal_exec.execution_time_ms == 500
        assert slow_exec.execution_time_ms == 5000

    def test_execution_with_complex_state(self):
        """Test execution with complex nested state."""
        state = {
            "steps": [
                {"step": 1, "action": "fetch_data", "status": "completed"},
                {"step": 2, "action": "analyze", "status": "in_progress"},
            ],
            "metrics": {"items_processed": 1500, "errors": 0},
            "cache_hits": 3,
        }

        execution = AgentExecutionEntity(
            id=1,
            agent_id=uuid4(),
            query="Complex multi-step analysis",
            status="running",
            state=state,
            progress=50,
        )

        assert execution.state == state
        assert len(execution.state["steps"]) == 2
        assert execution.state["metrics"]["items_processed"] == 1500

    def test_execution_with_task_id(self):
        """Test execution linked to a task."""
        execution = AgentExecutionEntity(
            id=1,
            agent_id=uuid4(),
            query="Create newsletter draft",
            status="completed",
            task_id="task_2025_001_newsletter",
            result="Draft created successfully",
        )

        assert execution.task_id == "task_2025_001_newsletter"
        assert execution.result == "Draft created successfully"

    def test_execution_triggered_by_another_user(self):
        """Test execution triggered by a different user."""
        agent_id = uuid4()
        triggered_by_id = uuid4()

        execution = AgentExecutionEntity(
            id=1,
            agent_id=agent_id,
            query="Review budget",
            status="completed",
            triggered_by_id=triggered_by_id,
        )

        assert execution.triggered_by_id == triggered_by_id
        assert execution.triggered_by_id != agent_id

    def test_execution_timestamps(self):
        """Test execution creation and update timestamps."""
        created_at = datetime(2025, 1, 1, 10, 0, 0)
        updated_at = datetime(2025, 1, 1, 10, 5, 30)

        execution = AgentExecutionEntity(
            id=1,
            agent_id=uuid4(),
            query="Test query",
            status="completed",
            created_at=created_at,
            updated_at=updated_at,
        )

        assert execution.created_at == created_at
        assert execution.updated_at == updated_at
        assert execution.updated_at > execution.created_at

    def test_execution_with_empty_result_and_error(self):
        """Test execution where result and error_message are both empty."""
        execution = AgentExecutionEntity(
            id=1,
            agent_id=uuid4(),
            query="Pending query",
            status="pending",
            result="",
            error_message="",
        )

        assert execution.result == ""
        assert execution.error_message == ""

    def test_execution_long_query_and_result(self):
        """Test execution with long query and result strings."""
        long_query = "A" * 5000
        long_result = "B" * 10000

        execution = AgentExecutionEntity(
            id=1,
            agent_id=uuid4(),
            query=long_query,
            status="completed",
            result=long_result,
            success=True,
        )

        assert len(execution.query) == 5000
        assert len(execution.result) == 10000
