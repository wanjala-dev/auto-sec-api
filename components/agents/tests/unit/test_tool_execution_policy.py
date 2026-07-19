"""Unit tests for ToolExecutionPolicy and ExecutionModeDecision."""

from components.agents.domain.policies.tool_execution_policy import (
    ToolExecutionPolicy,
    ExecutionModeDecision,
)
from components.agents.domain.enums import ExecutionMode


class TestExecutionModeDecision:
    """Tests for ExecutionModeDecision — output of execution policy."""

    def test_create_decision_llm_mode(self):
        """Test creating a decision for LLM mode."""
        decision = ExecutionModeDecision(
            mode=ExecutionMode.LLM,
            reason="Operation requires reasoning",
        )

        assert decision.mode == ExecutionMode.LLM
        assert decision.reason == "Operation requires reasoning"
        assert decision.cache_key is None
        assert decision.ttl_seconds == 0

    def test_create_decision_cached_mode(self):
        """Test creating a decision for cached mode."""
        cache_key = "abc123def456"

        decision = ExecutionModeDecision(
            mode=ExecutionMode.CACHED,
            reason="Found in cache",
            cache_key=cache_key,
            ttl_seconds=300,
        )

        assert decision.mode == ExecutionMode.CACHED
        assert decision.cache_key == cache_key
        assert decision.ttl_seconds == 300

    def test_create_decision_rules_based_mode(self):
        """Test creating a decision for rules-based mode."""
        decision = ExecutionModeDecision(
            mode=ExecutionMode.RULES_BASED,
            reason="Deterministic operation",
            cache_key="xyz789",
            ttl_seconds=300,
        )

        assert decision.mode == ExecutionMode.RULES_BASED
        assert decision.reason == "Deterministic operation"
        assert decision.cache_key == "xyz789"
        assert decision.ttl_seconds == 300

    def test_decision_is_llm_required_property(self):
        """Test is_llm_required property."""
        llm_decision = ExecutionModeDecision(
            mode=ExecutionMode.LLM,
            reason="Test",
        )

        non_llm_decision = ExecutionModeDecision(
            mode=ExecutionMode.RULES_BASED,
            reason="Test",
        )

        assert llm_decision.is_llm_required is True
        assert non_llm_decision.is_llm_required is False

    def test_decision_is_cacheable_property(self):
        """Test is_cacheable property."""
        cached_decision = ExecutionModeDecision(
            mode=ExecutionMode.CACHED,
            reason="Test",
        )

        non_cached_decision = ExecutionModeDecision(
            mode=ExecutionMode.LLM,
            reason="Test",
        )

        assert cached_decision.is_cacheable is True
        assert non_cached_decision.is_cacheable is False

    def test_decision_is_rules_based_property(self):
        """Test is_rules_based property."""
        rules_decision = ExecutionModeDecision(
            mode=ExecutionMode.RULES_BASED,
            reason="Test",
        )

        llm_decision = ExecutionModeDecision(
            mode=ExecutionMode.LLM,
            reason="Test",
        )

        assert rules_decision.is_rules_based is True
        assert llm_decision.is_rules_based is False

    def test_decision_is_frozen(self):
        """Test that ExecutionModeDecision is immutable."""
        decision = ExecutionModeDecision(mode=ExecutionMode.LLM, reason="Test")

        try:
            decision.mode = ExecutionMode.RULES_BASED
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected


class TestToolExecutionPolicy:
    """Tests for ToolExecutionPolicy — decides execution path."""

    def test_evaluate_require_llm_config_forces_llm(self):
        """Test that require_llm in config forces LLM mode."""
        policy = ToolExecutionPolicy()

        decision = policy.evaluate(
            operation="list",
            params={},
            tool_config={"require_llm": True},
            access_strategy="orm",
        )

        assert decision.mode == ExecutionMode.LLM
        assert "requires LLM" in decision.reason

    def test_evaluate_deterministic_operations(self):
        """Test deterministic operations use rules-based mode."""
        policy = ToolExecutionPolicy()

        deterministic_ops = ["list", "get", "count", "lookup", "filter",
                            "exists", "health_check", "schema", "status"]

        for op in deterministic_ops:
            decision = policy.evaluate(
                operation=op,
                params={},
                tool_config={},
                access_strategy="orm",
            )

            assert decision.mode == ExecutionMode.RULES_BASED
            assert "deterministic" in decision.reason.lower()

    def test_evaluate_llm_required_operations(self):
        """Test LLM-required operations use LLM mode."""
        policy = ToolExecutionPolicy()

        llm_ops = ["summarize", "analyze", "plan", "reason", "code_generate",
                  "multi_step", "synthesize", "orchestrate", "deep_run",
                  "draft", "create_strategy"]

        for op in llm_ops:
            decision = policy.evaluate(
                operation=op,
                params={},
                tool_config={},
                access_strategy="orm",
            )

            assert decision.mode == ExecutionMode.LLM
            assert "requires LLM" in decision.reason

    def test_evaluate_operation_case_insensitive(self):
        """Test that operation names are case insensitive."""
        policy = ToolExecutionPolicy()

        result_upper = policy.evaluate(
            operation="LIST",
            params={},
            tool_config={},
            access_strategy="orm",
        )

        result_mixed = policy.evaluate(
            operation="LiSt",
            params={},
            tool_config={},
            access_strategy="orm",
        )

        assert result_upper.mode == ExecutionMode.RULES_BASED
        assert result_mixed.mode == ExecutionMode.RULES_BASED

    def test_evaluate_operation_with_whitespace(self):
        """Test that operation names with whitespace are trimmed."""
        policy = ToolExecutionPolicy()

        decision = policy.evaluate(
            operation="  list  ",
            params={},
            tool_config={},
            access_strategy="orm",
        )

        assert decision.mode == ExecutionMode.RULES_BASED

    def test_evaluate_cache_hit_returns_cached(self):
        """Test that cache hits return CACHED mode."""
        policy = ToolExecutionPolicy()

        cache_key = policy._build_cache_key(
            operation="get",
            params={"id": 123},
            access_strategy="orm",
        )

        decision = policy.evaluate(
            operation="get",
            params={"id": 123},
            tool_config={},
            access_strategy="orm",
            recent_cache_keys=frozenset([cache_key]),
        )

        assert decision.mode == ExecutionMode.CACHED
        assert decision.cache_key == cache_key

    def test_evaluate_simple_deterministic_params(self):
        """Test deterministic operations with simple params use rules."""
        policy = ToolExecutionPolicy()

        simple_params = {"id": 123, "status": "active"}

        decision = policy.evaluate(
            operation="list",
            params=simple_params,
            tool_config={},
            access_strategy="orm",
        )

        assert decision.mode == ExecutionMode.RULES_BASED

    def test_evaluate_natural_language_params_forces_llm(self):
        """Test that long string params force LLM mode."""
        policy = ToolExecutionPolicy()

        nl_params = {"query": "x" * 300}  # Long string

        decision = policy.evaluate(
            operation="list",
            params=nl_params,
            tool_config={},
            access_strategy="orm",
        )

        assert decision.mode == ExecutionMode.LLM
        assert "natural-language" in decision.reason

    def test_evaluate_question_mark_forces_llm(self):
        """Test that question marks in params force LLM."""
        policy = ToolExecutionPolicy()

        params_with_question = {"query": "What is the budget?"}

        decision = policy.evaluate(
            operation="list",
            params=params_with_question,
            tool_config={},
            access_strategy="orm",
        )

        assert decision.mode == ExecutionMode.LLM

    def test_evaluate_default_fallback_to_llm(self):
        """Test that unclassified operations default to LLM."""
        policy = ToolExecutionPolicy()

        decision = policy.evaluate(
            operation="mysterious_operation",
            params={},
            tool_config={},
            access_strategy="orm",
        )

        assert decision.mode == ExecutionMode.LLM
        assert "default" in decision.reason

    def test_evaluate_cache_ttl_for_deterministic(self):
        """Test that deterministic operations get cache TTL."""
        policy = ToolExecutionPolicy()

        decision = policy.evaluate(
            operation="get",
            params={"id": 1},
            tool_config={},
            access_strategy="orm",
        )

        assert decision.ttl_seconds > 0

    def test_build_cache_key_deterministic(self):
        """Test that same inputs produce same cache key."""
        policy = ToolExecutionPolicy()

        key1 = policy._build_cache_key(
            operation="get",
            params={"id": 123},
            access_strategy="orm",
        )

        key2 = policy._build_cache_key(
            operation="get",
            params={"id": 123},
            access_strategy="orm",
        )

        assert key1 == key2

    def test_build_cache_key_different_for_different_inputs(self):
        """Test that different inputs produce different cache keys."""
        policy = ToolExecutionPolicy()

        key1 = policy._build_cache_key(
            operation="get",
            params={"id": 123},
            access_strategy="orm",
        )

        key2 = policy._build_cache_key(
            operation="get",
            params={"id": 456},
            access_strategy="orm",
        )

        assert key1 != key2

    def test_build_cache_key_operation_matters(self):
        """Test that operation name affects cache key."""
        policy = ToolExecutionPolicy()

        key1 = policy._build_cache_key(
            operation="list",
            params={},
            access_strategy="orm",
        )

        key2 = policy._build_cache_key(
            operation="get",
            params={},
            access_strategy="orm",
        )

        assert key1 != key2

    def test_build_cache_key_strategy_matters(self):
        """Test that access strategy affects cache key."""
        policy = ToolExecutionPolicy()

        key1 = policy._build_cache_key(
            operation="list",
            params={},
            access_strategy="orm",
        )

        key2 = policy._build_cache_key(
            operation="list",
            params={},
            access_strategy="web",
        )

        assert key1 != key2

    def test_has_nl_params_long_string(self):
        """Test detection of natural language in long strings."""
        policy = ToolExecutionPolicy()

        has_nl = policy._has_nl_params({"text": "x" * 300})

        assert has_nl is True

    def test_has_nl_params_question_mark(self):
        """Test detection of natural language with question mark."""
        policy = ToolExecutionPolicy()

        has_nl = policy._has_nl_params({"query": "What is this?"})

        assert has_nl is True

    def test_has_nl_params_short_string_no_question(self):
        """Test that short strings without questions don't trigger NL detection."""
        policy = ToolExecutionPolicy()

        has_nl = policy._has_nl_params({"id": "short"})

        assert has_nl is False

    def test_has_nl_params_numeric_values(self):
        """Test that numeric values don't trigger NL detection."""
        policy = ToolExecutionPolicy()

        has_nl = policy._has_nl_params({"count": 1000, "offset": 0})

        assert has_nl is False

    def test_has_nl_params_mixed_values(self):
        """Test NL detection with mixed value types."""
        policy = ToolExecutionPolicy()

        has_nl = policy._has_nl_params({
            "id": 123,
            "status": "active",
            "query": "very long question string " * 20,
        })

        assert has_nl is True

    def test_evaluate_deterministic_with_nl_uses_llm(self):
        """Test that deterministic ops with NL params use LLM."""
        policy = ToolExecutionPolicy()

        decision = policy.evaluate(
            operation="list",
            params={"query": "Tell me about the budgets?"},
            tool_config={},
            access_strategy="orm",
        )

        assert decision.mode == ExecutionMode.LLM

    def test_evaluate_llm_required_always_llm(self):
        """Test that LLM-required ops always use LLM."""
        policy = ToolExecutionPolicy()

        decision = policy.evaluate(
            operation="plan",
            params={"simple": "data"},
            tool_config={},
            access_strategy="orm",
        )

        assert decision.mode == ExecutionMode.LLM

    def test_evaluate_with_empty_cache_keys(self):
        """Test evaluation with empty cache keys frozenset."""
        policy = ToolExecutionPolicy()

        decision = policy.evaluate(
            operation="list",
            params={},
            tool_config={},
            access_strategy="orm",
            recent_cache_keys=frozenset(),
        )

        assert decision.mode == ExecutionMode.RULES_BASED

    def test_evaluate_with_none_cache_keys(self):
        """Test evaluation with None cache keys."""
        policy = ToolExecutionPolicy()

        decision = policy.evaluate(
            operation="list",
            params={},
            tool_config={},
            access_strategy="orm",
            recent_cache_keys=None,
        )

        assert decision.mode == ExecutionMode.RULES_BASED

    def test_decision_reason_always_present(self):
        """Test that all decisions include a reason."""
        policy = ToolExecutionPolicy()

        test_cases = [
            ("list", {}, {"require_llm": True}),
            ("get", {"id": 1}, {}),
            ("analyze", {}, {}),
            ("unknown_op", {}, {}),
        ]

        for operation, params, tool_config in test_cases:
            decision = policy.evaluate(
                operation=operation,
                params=params,
                tool_config=tool_config,
                access_strategy="orm",
            )

            assert decision.reason
            assert len(decision.reason) > 0

    def test_cache_key_format(self):
        """Test that cache keys are SHA256 hex strings."""
        policy = ToolExecutionPolicy()

        key = policy._build_cache_key(
            operation="test",
            params={},
            access_strategy="orm",
        )

        # SHA256 hex string should be 64 chars
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)
