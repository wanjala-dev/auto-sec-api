"""Unit tests for ToolExecutionEntity and TokenUsage."""

from datetime import datetime
from uuid import uuid4

from components.agents.domain.entities.tool_execution_entity import (
    TokenUsage,
    ToolExecutionEntity,
)
from components.agents.domain.enums import (
    ExecutionMode,
    ModelTier,
    ToolExecutionStatus,
)


class TestTokenUsage:
    """Tests for TokenUsage — LLM token consumption tracking."""

    def test_create_minimal_token_usage(self):
        """Test creating token usage with default values."""
        tokens = TokenUsage()

        assert tokens.prompt_tokens == 0
        assert tokens.completion_tokens == 0
        assert tokens.total_tokens == 0
        assert tokens.model_name == ""
        assert tokens.model_tier == ModelTier.TIER_1

    def test_create_token_usage_with_values(self):
        """Test creating token usage with specific values."""
        tokens = TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model_name="gpt-4o",
            model_tier=ModelTier.TIER_2,
        )

        assert tokens.prompt_tokens == 100
        assert tokens.completion_tokens == 50
        assert tokens.total_tokens == 150
        assert tokens.model_name == "gpt-4o"
        assert tokens.model_tier == ModelTier.TIER_2

    def test_token_usage_is_frozen(self):
        """Test that TokenUsage is immutable."""
        tokens = TokenUsage(prompt_tokens=100)

        try:
            tokens.prompt_tokens = 200
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected

    def test_estimated_cost_tier_1(self):
        """Test cost estimation for tier 1 tokens."""
        tokens = TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model_tier=ModelTier.TIER_1,
        )

        # 150 tokens / 1000 * 0.0005 * 1.0 = 0.000075
        expected_cost = (150 / 1000) * 0.0005 * 1.0
        assert tokens.estimated_cost_usd == expected_cost

    def test_estimated_cost_tier_2(self):
        """Test cost estimation for tier 2 tokens."""
        tokens = TokenUsage(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            model_tier=ModelTier.TIER_2,
        )

        # 1500 tokens / 1000 * 0.0005 * 5.0 = 0.00375
        expected_cost = (1500 / 1000) * 0.0005 * 5.0
        assert tokens.estimated_cost_usd == expected_cost

    def test_estimated_cost_tier_3(self):
        """Test cost estimation for tier 3 tokens."""
        tokens = TokenUsage(
            prompt_tokens=5000,
            completion_tokens=2000,
            total_tokens=7000,
            model_tier=ModelTier.TIER_3,
        )

        # 7000 tokens / 1000 * 0.0005 * 20.0 = 0.07
        expected_cost = (7000 / 1000) * 0.0005 * 20.0
        assert tokens.estimated_cost_usd == expected_cost

    def test_estimated_cost_zero_tokens(self):
        """Test cost estimation with zero tokens."""
        tokens = TokenUsage(total_tokens=0)

        assert tokens.estimated_cost_usd == 0.0

    def test_token_usage_with_different_models(self):
        """Test token usage with different model names."""
        gpt_tokens = TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model_name="gpt-4o",
        )

        claude_tokens = TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model_name="claude-opus-4-6",
        )

        assert gpt_tokens.model_name == "gpt-4o"
        assert claude_tokens.model_name == "claude-opus-4-6"


class TestToolExecutionEntity:
    """Tests for ToolExecutionEntity — records of tool invocations."""

    def test_create_execution_minimal(self):
        """Test creating an execution with minimal required fields."""
        exec_id = uuid4()
        tool_id = uuid4()
        agent_id = uuid4()
        workspace_id = uuid4()

        execution = ToolExecutionEntity(
            execution_id=exec_id,
            tool_id=tool_id,
            agent_id=agent_id,
            workspace_id=workspace_id,
            operation="list",
            params={},
        )

        assert execution.execution_id == exec_id
        assert execution.tool_id == tool_id
        assert execution.agent_id == agent_id
        assert execution.workspace_id == workspace_id
        assert execution.operation == "list"
        assert execution.params == {}
        assert execution.execution_mode == ExecutionMode.LLM
        assert execution.access_strategy == ""
        assert execution.status == ToolExecutionStatus.PENDING
        assert execution.result is None
        assert execution.error_message is None
        assert execution.execution_time_ms is None
        assert execution.token_usage is None
        assert execution.cache_hit is False
        assert execution.created_at is None
        assert execution.completed_at is None

    def test_execution_factory_create(self):
        """Test ToolExecutionEntity.create() factory."""
        tool_id = uuid4()
        agent_id = uuid4()
        workspace_id = uuid4()

        execution = ToolExecutionEntity.create(
            tool_id=tool_id,
            agent_id=agent_id,
            workspace_id=workspace_id,
            operation="search",
            access_strategy="orm",
            params={"query": "budget"},
        )

        assert execution.execution_id is not None
        assert execution.tool_id == tool_id
        assert execution.agent_id == agent_id
        assert execution.workspace_id == workspace_id
        assert execution.operation == "search"
        assert execution.access_strategy == "orm"
        assert execution.params == {"query": "budget"}
        assert execution.status == ToolExecutionStatus.PENDING
        assert execution.created_at is not None

    def test_execution_factory_rehydrate(self):
        """Test ToolExecutionEntity.rehydrate() factory."""
        exec_id = uuid4()

        execution = ToolExecutionEntity.rehydrate(
            execution_id=exec_id,
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="get",
            access_strategy="orm",
            status=ToolExecutionStatus.COMPLETED,
        )

        assert execution.execution_id == exec_id
        assert execution.status == ToolExecutionStatus.COMPLETED

    def test_execution_mark_running(self):
        """Test mark_running() state transition."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="list",
            params={},
            status=ToolExecutionStatus.PENDING,
        )

        assert execution.status == ToolExecutionStatus.PENDING

        execution.mark_running()
        assert execution.status == ToolExecutionStatus.RUNNING

    def test_execution_mark_running_from_non_pending(self):
        """Test mark_running() fails from non-pending state."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="list",
            params={},
            status=ToolExecutionStatus.COMPLETED,
        )

        try:
            execution.mark_running()
            assert False, "Should not allow running from completed state"
        except ValueError as e:
            assert "Cannot start execution" in str(e)

    def test_execution_mark_completed(self):
        """Test mark_completed() records success."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="list",
            params={},
            status=ToolExecutionStatus.RUNNING,
        )

        result = [{"id": 1, "name": "Budget 1"}]
        token_usage = TokenUsage(
            prompt_tokens=50,
            completion_tokens=30,
            total_tokens=80,
            model_tier=ModelTier.TIER_1,
        )

        execution.mark_completed(
            result=result,
            execution_time_ms=1500,
            token_usage=token_usage,
            cache_hit=False,
        )

        assert execution.status == ToolExecutionStatus.COMPLETED
        assert execution.result == result
        assert execution.execution_time_ms == 1500
        assert execution.token_usage == token_usage
        assert execution.cache_hit is False
        assert execution.completed_at is not None

    def test_execution_mark_completed_with_cache_hit(self):
        """Test mark_completed() with cache hit."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="get",
            params={},
            status=ToolExecutionStatus.RUNNING,
        )

        result = "cached_result"

        execution.mark_completed(
            result=result,
            execution_time_ms=5,
            cache_hit=True,
        )

        assert execution.status == ToolExecutionStatus.COMPLETED
        assert execution.result == result
        assert execution.cache_hit is True
        assert execution.execution_time_ms == 5

    def test_execution_mark_failed(self):
        """Test mark_failed() records failure."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="list",
            params={},
            status=ToolExecutionStatus.RUNNING,
        )

        execution.mark_failed(
            error_message="Database connection timeout",
            execution_time_ms=30000,
        )

        assert execution.status == ToolExecutionStatus.FAILED
        assert execution.error_message == "Database connection timeout"
        assert execution.execution_time_ms == 30000
        assert execution.completed_at is not None

    def test_execution_mark_skipped(self):
        """Test mark_skipped() for rules-based bypass."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="list",
            params={},
            execution_mode=ExecutionMode.LLM,
        )

        execution.mark_skipped(reason="simple_deterministic_op")

        assert execution.status == ToolExecutionStatus.SKIPPED
        assert execution.error_message == "simple_deterministic_op"
        assert execution.execution_mode == ExecutionMode.RULES_BASED
        assert execution.execution_time_ms == 0
        assert execution.completed_at is not None

    def test_execution_is_billable_with_llm_tokens(self):
        """Test is_billable for LLM executions with tokens."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="analyze",
            params={},
            execution_mode=ExecutionMode.LLM,
            cache_hit=False,
        )

        execution.mark_completed(
            result="analysis",
            execution_time_ms=2000,
            token_usage=TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
        )

        assert execution.is_billable is True

    def test_execution_not_billable_cache_hit(self):
        """Test is_billable is False for cache hits."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="get",
            params={},
            execution_mode=ExecutionMode.LLM,
            cache_hit=True,
        )

        execution.mark_completed(
            result="cached",
            execution_time_ms=5,
            token_usage=TokenUsage(total_tokens=0),
        )

        assert execution.is_billable is False

    def test_execution_not_billable_rules_based(self):
        """Test is_billable is False for rules-based executions."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="list",
            params={},
            execution_mode=ExecutionMode.RULES_BASED,
        )

        execution.mark_completed(
            result="list",
            execution_time_ms=100,
        )

        assert execution.is_billable is False

    def test_execution_not_billable_no_tokens(self):
        """Test is_billable is False when no tokens used."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="status",
            params={},
            execution_mode=ExecutionMode.LLM,
        )

        execution.mark_completed(
            result="ok",
            execution_time_ms=50,
            token_usage=TokenUsage(total_tokens=0),
        )

        assert execution.is_billable is False

    def test_execution_cost_usd(self):
        """Test cost_usd calculation."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="analyze",
            params={},
            execution_mode=ExecutionMode.LLM,
        )

        token_usage = TokenUsage(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            model_tier=ModelTier.TIER_2,
        )

        execution.mark_completed(
            result="analysis",
            execution_time_ms=2000,
            token_usage=token_usage,
        )

        expected_cost = token_usage.estimated_cost_usd
        assert execution.cost_usd == expected_cost

    def test_execution_cost_usd_non_billable(self):
        """Test cost_usd is 0 for non-billable executions."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="list",
            params={},
            execution_mode=ExecutionMode.RULES_BASED,
        )

        execution.mark_completed(
            result="list",
            execution_time_ms=100,
        )

        assert execution.cost_usd == 0.0

    def test_execution_latency_bucket_fast(self):
        """Test latency_bucket for fast executions."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="get",
            params={},
        )

        execution.mark_completed(
            result="data",
            execution_time_ms=50,
        )

        assert execution.latency_bucket == "fast"

    def test_execution_latency_bucket_normal(self):
        """Test latency_bucket for normal executions."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="search",
            params={},
        )

        execution.mark_completed(
            result="results",
            execution_time_ms=500,
        )

        assert execution.latency_bucket == "normal"

    def test_execution_latency_bucket_slow(self):
        """Test latency_bucket for slow executions."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="analyze",
            params={},
        )

        execution.mark_completed(
            result="analysis",
            execution_time_ms=2000,
        )

        assert execution.latency_bucket == "slow"

    def test_execution_latency_bucket_very_slow(self):
        """Test latency_bucket for very slow executions."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="deep_run",
            params={},
        )

        execution.mark_completed(
            result="complex_result",
            execution_time_ms=10000,
        )

        assert execution.latency_bucket == "very_slow"

    def test_execution_latency_bucket_unknown(self):
        """Test latency_bucket when execution_time_ms is None."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="pending",
            params={},
        )

        assert execution.latency_bucket == "unknown"

    def test_execution_validate_execution_time_negative(self):
        """Test validation rejects negative execution time."""
        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="test",
            params={},
        )

        try:
            execution.mark_completed(
                result="data",
                execution_time_ms=-100,
            )
            assert False, "Should reject negative execution time"
        except ValueError as e:
            assert "execution_time_ms must be non-negative" in str(e)

    def test_execution_validate_execution_mode_invalid(self):
        """Test validation rejects invalid execution mode."""
        try:
            ToolExecutionEntity.create(
                tool_id=uuid4(),
                agent_id=uuid4(),
                workspace_id=uuid4(),
                operation="test",
                access_strategy="orm",
                execution_mode="invalid_mode",
            )
            assert False, "Should reject invalid execution mode"
        except ValueError as e:
            assert "Invalid execution mode" in str(e)

    def test_execution_validate_execution_mode_valid(self):
        """Test validation accepts valid execution modes."""
        for mode in [ExecutionMode.LLM, ExecutionMode.RULES_BASED, ExecutionMode.CACHED]:
            execution = ToolExecutionEntity.create(
                tool_id=uuid4(),
                agent_id=uuid4(),
                workspace_id=uuid4(),
                operation="test",
                access_strategy="orm",
                execution_mode=mode,
            )
            assert execution.execution_mode == mode

    def test_execution_with_params(self):
        """Test execution with various parameter structures."""
        simple_params = {"id": 123, "name": "test"}
        complex_params = {
            "filters": {
                "status": "active",
                "date_range": {"start": "2025-01-01", "end": "2025-12-31"},
            },
            "options": {"limit": 100, "offset": 0},
        }

        exec_simple = ToolExecutionEntity.create(
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="get",
            access_strategy="orm",
            params=simple_params,
        )

        exec_complex = ToolExecutionEntity.create(
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="search",
            access_strategy="orm",
            params=complex_params,
        )

        assert exec_simple.params == simple_params
        assert exec_complex.params == complex_params

    def test_execution_timestamps(self):
        """Test execution timestamps."""
        now = datetime.utcnow()

        execution = ToolExecutionEntity(
            execution_id=uuid4(),
            tool_id=uuid4(),
            agent_id=uuid4(),
            workspace_id=uuid4(),
            operation="test",
            params={},
            created_at=now,
        )

        execution.mark_completed(result="ok", execution_time_ms=100)

        assert execution.created_at == now
        assert execution.completed_at is not None
        assert execution.completed_at >= execution.created_at
