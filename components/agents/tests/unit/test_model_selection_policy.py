"""Unit tests for ModelSelectionPolicy and ModelSelectionResult."""

from components.agents.domain.policies.model_selection_policy import (
    ModelSelectionPolicy,
    ModelSelectionResult,
)
from components.agents.domain.enums import ModelTier


class TestModelSelectionResult:
    """Tests for ModelSelectionResult — output of model selection."""

    def test_create_result_minimal(self):
        """Test creating a selection result with minimal fields."""
        result = ModelSelectionResult(
            tier=ModelTier.TIER_1,
            reason="Simple operation",
        )

        assert result.tier == ModelTier.TIER_1
        assert result.reason == "Simple operation"
        assert result.override_model is None

    def test_create_result_with_override_model(self):
        """Test creating a selection result with explicit model override."""
        result = ModelSelectionResult(
            tier=ModelTier.TIER_3,
            reason="Complex reasoning task",
            override_model="claude-opus-4-6",
        )

        assert result.tier == ModelTier.TIER_3
        assert result.reason == "Complex reasoning task"
        assert result.override_model == "claude-opus-4-6"

    def test_result_cost_multiplier_tier_1(self):
        """Test cost multiplier for tier 1."""
        result = ModelSelectionResult(
            tier=ModelTier.TIER_1,
            reason="Test",
        )

        assert result.cost_multiplier == 1.0

    def test_result_cost_multiplier_tier_2(self):
        """Test cost multiplier for tier 2."""
        result = ModelSelectionResult(
            tier=ModelTier.TIER_2,
            reason="Test",
        )

        assert result.cost_multiplier == 5.0

    def test_result_cost_multiplier_tier_3(self):
        """Test cost multiplier for tier 3."""
        result = ModelSelectionResult(
            tier=ModelTier.TIER_3,
            reason="Test",
        )

        assert result.cost_multiplier == 20.0

    def test_result_is_frozen(self):
        """Test that ModelSelectionResult is immutable."""
        result = ModelSelectionResult(tier=ModelTier.TIER_1, reason="Test")

        try:
            result.tier = ModelTier.TIER_3
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected


class TestModelSelectionPolicy:
    """Tests for ModelSelectionPolicy — determines model tier for operations."""

    def test_evaluate_tier_1_operations(self):
        """Test tier 1 operations use cheapest model."""
        policy = ModelSelectionPolicy()

        tier1_ops = ["list", "get", "search", "count", "classify", "extract",
                     "validate", "lookup", "filter"]

        for op in tier1_ops:
            result = policy.evaluate(
                operation=op,
                params={},
                tool_config={},
            )

            assert result.tier == ModelTier.TIER_1
            assert "simple" in result.reason.lower()

    def test_evaluate_tier_2_operations(self):
        """Test tier 2 operations use mid-range model."""
        policy = ModelSelectionPolicy()

        tier2_ops = ["summarize", "describe", "compare", "translate", "format",
                     "transform", "generate_template", "draft"]

        for op in tier2_ops:
            result = policy.evaluate(
                operation=op,
                params={},
                tool_config={},
            )

            assert result.tier == ModelTier.TIER_2
            assert "moderate" in result.reason.lower()

    def test_evaluate_tier_3_operations(self):
        """Test tier 3 operations use powerful model."""
        policy = ModelSelectionPolicy()

        tier3_ops = ["plan", "reason", "analyze", "code_generate", "multi_step",
                     "create_strategy", "deep_run", "orchestrate", "synthesize"]

        for op in tier3_ops:
            result = policy.evaluate(
                operation=op,
                params={},
                tool_config={},
            )

            assert result.tier == ModelTier.TIER_3
            assert "complex" in result.reason.lower()

    def test_evaluate_operation_case_insensitive(self):
        """Test that operation names are case insensitive."""
        policy = ModelSelectionPolicy()

        result_upper = policy.evaluate(
            operation="LIST",
            params={},
            tool_config={},
        )

        result_mixed = policy.evaluate(
            operation="LiSt",
            params={},
            tool_config={},
        )

        assert result_upper.tier == ModelTier.TIER_1
        assert result_mixed.tier == ModelTier.TIER_1

    def test_evaluate_operation_with_whitespace(self):
        """Test that operation names with whitespace are trimmed."""
        policy = ModelSelectionPolicy()

        result = policy.evaluate(
            operation="  analyze  ",
            params={},
            tool_config={},
        )

        assert result.tier == ModelTier.TIER_3

    def test_evaluate_forced_tier_override(self):
        """Test that explicit tier in config takes precedence."""
        policy = ModelSelectionPolicy()

        result = policy.evaluate(
            operation="list",  # Would be tier 1
            params={},
            tool_config={"model_tier": ModelTier.TIER_3},
        )

        assert result.tier == ModelTier.TIER_3
        assert "forces" in result.reason

    def test_evaluate_forced_model_override(self):
        """Test that explicit model name in config is respected."""
        policy = ModelSelectionPolicy()

        result = policy.evaluate(
            operation="list",
            params={},
            tool_config={"model_name": "custom-model-v1"},
        )

        assert result.override_model == "custom-model-v1"
        assert "forces model" in result.reason

    def test_evaluate_large_payload_tier_bump(self):
        """Test that large payloads bump tier up."""
        policy = ModelSelectionPolicy()

        # Create a payload larger than LARGE_PAYLOAD_BYTES (4000)
        large_params = {"data": "x" * 5000}

        result = policy.evaluate(
            operation="unknown_op",
            params=large_params,
            tool_config={},
        )

        assert result.tier == ModelTier.TIER_2
        assert "payload size" in result.reason

    def test_evaluate_very_large_payload_tier_3(self):
        """Test that very large payloads force tier 3."""
        policy = ModelSelectionPolicy()

        # Create payload larger than VERY_LARGE_PAYLOAD_BYTES (16000)
        very_large_params = {"data": "x" * 20000}

        result = policy.evaluate(
            operation="unknown_op",
            params=very_large_params,
            tool_config={},
        )

        assert result.tier == ModelTier.TIER_3
        assert "payload size" in result.reason

    def test_evaluate_default_tier_2(self):
        """Test default tier is tier 2 for unclassified operations."""
        policy = ModelSelectionPolicy()

        result = policy.evaluate(
            operation="mysterious_operation",
            params={},
            tool_config={},
        )

        assert result.tier == ModelTier.TIER_2
        assert "default" in result.reason

    def test_evaluate_operation_precedence_over_payload_size(self):
        """Test that operation classification takes precedence over payload size."""
        policy = ModelSelectionPolicy()

        # Large params would suggest tier 2+, but list is tier 1
        result = policy.evaluate(
            operation="list",
            params={"data": "x" * 5000},
            tool_config={},
        )

        assert result.tier == ModelTier.TIER_1
        assert "list" in result.reason.lower()

    def test_evaluate_forced_tier_overrides_everything(self):
        """Test that forced tier beats all other heuristics."""
        policy = ModelSelectionPolicy()

        result = policy.evaluate(
            operation="plan",  # Would be tier 3
            params={"data": "x" * 100},  # Small payload
            tool_config={"model_tier": ModelTier.TIER_1},
        )

        assert result.tier == ModelTier.TIER_1

    def test_evaluate_with_agent_type(self):
        """Test that agent_type parameter is accepted."""
        policy = ModelSelectionPolicy()

        result = policy.evaluate(
            operation="analyze",
            params={},
            tool_config={},
            agent_type="budget_analyst",
        )

        assert result.tier == ModelTier.TIER_3

    def test_estimate_payload_size_simple(self):
        """Test payload size estimation for simple structures."""
        policy = ModelSelectionPolicy()

        params = {"id": 123, "name": "test"}
        size = policy._estimate_payload_size(params)

        assert size > 0
        assert isinstance(size, int)

    def test_estimate_payload_size_nested(self):
        """Test payload size estimation for nested structures."""
        policy = ModelSelectionPolicy()

        params = {
            "data": {
                "nested": {
                    "deep": [1, 2, 3],
                    "text": "Hello world",
                },
            },
        }
        size = policy._estimate_payload_size(params)

        assert size > 0

    def test_estimate_payload_size_with_non_serializable(self):
        """Test payload size estimation handles non-JSON-serializable objects."""
        policy = ModelSelectionPolicy()

        # datetime objects aren't directly JSON serializable
        from datetime import datetime

        params = {"timestamp": datetime.now()}
        size = policy._estimate_payload_size(params)

        # Should use str() fallback and still get a size
        assert size > 0

    def test_estimate_payload_size_empty(self):
        """Test payload size estimation for empty params."""
        policy = ModelSelectionPolicy()

        size = policy._estimate_payload_size({})

        assert size >= 0

    def test_evaluation_result_contains_reason(self):
        """Test that all evaluation results include a reason."""
        policy = ModelSelectionPolicy()

        operations = ["list", "analyze", "unknown_op"]
        for op in operations:
            result = policy.evaluate(
                operation=op,
                params={},
                tool_config={},
            )

            assert result.reason
            assert len(result.reason) > 0
            assert isinstance(result.reason, str)

    def test_evaluate_empty_operation_defaults_to_tier_2(self):
        """Test that empty operation string defaults to tier 2."""
        policy = ModelSelectionPolicy()

        result = policy.evaluate(
            operation="",
            params={},
            tool_config={},
        )

        assert result.tier == ModelTier.TIER_2

    def test_evaluate_with_payload_content_types(self):
        """Test payload size calculation with different content types."""
        policy = ModelSelectionPolicy()

        # String payload
        result_str = policy.evaluate(
            operation="unknown",
            params={"text": "x" * 5000},
            tool_config={},
        )

        # Numeric payload (should be smaller)
        result_num = policy.evaluate(
            operation="unknown",
            params={"numbers": list(range(1000))},
            tool_config={},
        )

        assert result_str.tier == ModelTier.TIER_2
        # Numeric array might be tier 1 or 2 depending on JSON size

    def test_evaluate_tier_3_precedence_over_payload(self):
        """Test that tier 3 operations force tier 3 regardless of payload."""
        policy = ModelSelectionPolicy()

        result = policy.evaluate(
            operation="deep_run",
            params={"small": "value"},
            tool_config={},
        )

        assert result.tier == ModelTier.TIER_3

    def test_model_selection_with_invalid_tier_in_config(self):
        """Test handling of invalid tier in tool config."""
        policy = ModelSelectionPolicy()

        result = policy.evaluate(
            operation="list",
            params={},
            tool_config={"model_tier": "invalid_tier"},
        )

        # Should fall through to operation classification
        assert result.tier == ModelTier.TIER_1
