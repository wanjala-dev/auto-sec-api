"""Unit tests for AgentConfigService and AgentTypeConfig."""

from components.agents.domain.services.agent_config_service import (
    AgentConfigService,
    AgentTypeConfig,
    ProfileDetails,
)


class TestAgentTypeConfig:
    """Tests for AgentTypeConfig — agent type definitions."""

    def test_create_minimal_config(self):
        """Test creating a minimal agent type config."""
        config = AgentTypeConfig(
            slug="budget_analyst",
            name="Budget Analyst",
        )

        assert config.slug == "budget_analyst"
        assert config.name == "Budget Analyst"
        assert config.description == ""
        assert config.default_config == {}
        assert config.aliases == []
        assert config.required_actions == []
        assert config.allowed_tools == []
        assert config.department_tags == []
        assert config.default_run_config == {}
        assert config.class_path == ""
        assert config.is_active is True

    def test_create_full_config(self):
        """Test creating a full agent type config."""
        default_config = {
            "temperature": 0.7,
            "max_tokens": 2000,
            "profile": {
                "summary": "Expert in budget analysis and forecasting",
                "capabilities": ["budgeting", "forecasting", "analysis"],
            },
        }
        default_run_config = {"timeout": 120, "retries": 3}

        config = AgentTypeConfig(
            slug="budget_analyst",
            name="Budget Analyst",
            description="Analyzes budgets and provides financial insights",
            default_config=default_config,
            aliases=["financial_analyst", "budget_expert"],
            required_actions=["read_budget", "analyze_trends"],
            allowed_tools=["list_budgets", "analyze_budget", "forecast"],
            department_tags=["finance", "operations"],
            default_run_config=default_run_config,
            class_path="agents.budget.BudgetAnalyst",
            is_active=True,
        )

        assert config.slug == "budget_analyst"
        assert config.name == "Budget Analyst"
        assert config.description == "Analyzes budgets and provides financial insights"
        assert config.default_config == default_config
        assert config.aliases == ["financial_analyst", "budget_expert"]
        assert config.required_actions == ["read_budget", "analyze_trends"]
        assert config.allowed_tools == ["list_budgets", "analyze_budget", "forecast"]
        assert config.department_tags == ["finance", "operations"]
        assert config.default_run_config == default_run_config
        assert config.class_path == "agents.budget.BudgetAnalyst"
        assert config.is_active is True

    def test_agent_type_config_is_frozen(self):
        """Test that AgentTypeConfig is immutable."""
        config = AgentTypeConfig(slug="test", name="Test")

        try:
            config.is_active = False
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected


class TestProfileDetails:
    """Tests for ProfileDetails — extracted profile information."""

    def test_create_profile_details(self):
        """Test creating profile details."""
        details = ProfileDetails(
            summary="Expert budget analyst",
            capabilities=["forecasting", "analysis", "reporting"],
            examples=["What is the budget forecast?", "Show spending trends"],
        )

        assert details.summary == "Expert budget analyst"
        assert details.capabilities == ["forecasting", "analysis", "reporting"]
        assert details.examples == ["What is the budget forecast?", "Show spending trends"]

    def test_profile_details_is_frozen(self):
        """Test that ProfileDetails is immutable."""
        details = ProfileDetails(
            summary="Test",
            capabilities=[],
            examples=[],
        )

        try:
            details.summary = "Modified"
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected


class TestAgentConfigService:
    """Tests for AgentConfigService — configuration management."""

    def test_merge_config_empty_override(self):
        """Test merging config with no override."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget",
            default_config={"temperature": 0.7, "max_tokens": 1000},
        )

        merged = AgentConfigService.merge_config(agent_type)

        assert merged == {"temperature": 0.7, "max_tokens": 1000}

    def test_merge_config_with_override(self):
        """Test merging config with override values."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget",
            default_config={"temperature": 0.7, "max_tokens": 1000},
        )

        override = {"temperature": 0.9}

        merged = AgentConfigService.merge_config(agent_type, override)

        assert merged["temperature"] == 0.9
        assert merged["max_tokens"] == 1000

    def test_merge_config_adds_allowed_tools(self):
        """Test merge adds allowed_tools from agent type."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget",
            default_config={},
            allowed_tools=["list_budgets", "analyze_budget"],
        )

        merged = AgentConfigService.merge_config(agent_type)

        assert "allowed_tools" in merged
        assert merged["allowed_tools"] == ["list_budgets", "analyze_budget"]

    def test_merge_config_adds_required_actions(self):
        """Test merge adds required_actions from agent type."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget",
            default_config={},
            required_actions=["read_budget", "write_report"],
        )

        merged = AgentConfigService.merge_config(agent_type)

        assert "required_actions" in merged
        assert merged["required_actions"] == ["read_budget", "write_report"]

    def test_merge_config_override_preserves_existing_allowed_tools(self):
        """Test that override allowed_tools in base config is preserved."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget",
            default_config={"allowed_tools": ["existing_tool"]},
            allowed_tools=["list_budgets"],
        )

        merged = AgentConfigService.merge_config(agent_type)

        assert merged["allowed_tools"] == ["existing_tool"]

    def test_merge_config_does_not_mutate_inputs(self):
        """Test that merge_config doesn't mutate original objects."""
        original_config = {"temperature": 0.7}
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget",
            default_config=original_config,
        )

        override = {"max_tokens": 2000}

        merged = AgentConfigService.merge_config(agent_type, override)

        # Original shouldn't be modified
        assert "max_tokens" not in original_config
        # But merged should have both
        assert merged["temperature"] == 0.7
        assert merged["max_tokens"] == 2000

    def test_extract_profile_details_from_config(self):
        """Test extracting profile details from agent config."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget Analyst",
            description="Analyzes budgets",
            default_config={
                "profile": {
                    "summary": "Expert in financial planning",
                    "capabilities": ["forecasting", "trend analysis"],
                    "sample_prompts": [
                        "What is the Q1 budget?",
                        "Show spending trends",
                    ],
                }
            },
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert profile.summary == "Expert in financial planning"
        assert profile.capabilities == ["forecasting", "trend analysis"]
        assert profile.examples == ["What is the Q1 budget?", "Show spending trends"]

    def test_extract_profile_details_fallback_examples_field(self):
        """Test fallback to 'examples' field when sample_prompts missing."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget",
            default_config={
                "profile": {
                    "summary": "Budget expert",
                    "capabilities": ["analysis"],
                    "examples": ["Example 1", "Example 2"],
                }
            },
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert profile.examples == ["Example 1", "Example 2"]

    def test_extract_profile_details_no_profile_section(self):
        """Test extraction when profile section doesn't exist."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget Analyst",
            description="Analyzes budgets",
            default_config={"temperature": 0.7},
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert profile.summary == "Analyzes budgets"
        assert profile.capabilities == []
        assert len(profile.examples) == 3
        assert "Budget Analyst" in profile.examples[0]

    def test_extract_profile_details_fallback_to_description(self):
        """Test fallback to description when profile.summary missing."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="Budget Analyst",
            description="Expert financial analyst",
            default_config={"profile": {}},
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert profile.summary == "Expert financial analyst"

    def test_extract_profile_details_default_summary(self):
        """Test default summary when nothing available."""
        agent_type = AgentTypeConfig(
            slug="budget",
            name="BudgetTool",
            description="",
            default_config={},
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert "BudgetTool" in profile.summary
        assert "tasks" in profile.summary

    def test_extract_profile_details_auto_generated_examples(self):
        """Test auto-generated examples from agent name."""
        agent_type = AgentTypeConfig(
            slug="newsletter",
            name="Newsletter Creator",
            default_config={},
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert len(profile.examples) == 3
        assert "Newsletter Creator" in profile.examples[0]

    def test_extract_profile_details_filters_empty_capabilities(self):
        """Test that empty capabilities are filtered out."""
        agent_type = AgentTypeConfig(
            slug="test",
            name="Test",
            default_config={
                "profile": {
                    "summary": "Test",
                    "capabilities": ["real_cap", "", None, "another_cap"],
                }
            },
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert profile.capabilities == ["real_cap", "another_cap"]

    def test_extract_profile_details_filters_empty_examples(self):
        """Test that empty examples are filtered out."""
        agent_type = AgentTypeConfig(
            slug="test",
            name="Test",
            default_config={
                "profile": {
                    "summary": "Test",
                    "sample_prompts": ["real_example", "", None, "another"],
                }
            },
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert profile.examples == ["real_example", "another"]

    def test_extract_profile_details_handles_non_dict_profile(self):
        """Test extraction when profile is not a dict."""
        agent_type = AgentTypeConfig(
            slug="test",
            name="Test Agent",
            description="A test agent",
            default_config={"profile": "not a dict"},
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert profile.summary == "A test agent"
        assert profile.capabilities == []

    def test_resolve_alias_with_mapping(self):
        """Test resolving an alias using alias map."""
        alias_map = {
            "budget_expert": "budget_analyst",
            "task_master": "task_runner",
        }

        result = AgentConfigService.resolve_alias("budget_expert", alias_map)

        assert result == "budget_analyst"

    def test_resolve_alias_no_mapping(self):
        """Test resolving an alias with no mapping returns original."""
        alias_map = {"budget_expert": "budget_analyst"}

        result = AgentConfigService.resolve_alias("unknown", alias_map)

        assert result == "unknown"

    def test_resolve_alias_empty_map(self):
        """Test resolving with empty alias map."""
        result = AgentConfigService.resolve_alias("some_slug", {})

        assert result == "some_slug"

    def test_build_default_display_name(self):
        """Test building default display name."""
        name = AgentConfigService.build_default_display_name(
            agent_type_name="Budget Analyst",
            workspace_id="workspace_123",
        )

        assert "Budget Analyst" in name
        assert "workspace_123" in name

    def test_build_default_display_name_with_uuid(self):
        """Test building default display name with UUID."""
        from uuid import uuid4

        workspace_id = uuid4()

        name = AgentConfigService.build_default_display_name(
            agent_type_name="Newsletter Creator",
            workspace_id=str(workspace_id),
        )

        assert "Newsletter Creator" in name
        assert str(workspace_id) in name

    def test_merge_config_complex_nested_override(self):
        """Test merging with complex nested override."""
        agent_type = AgentTypeConfig(
            slug="advanced",
            name="Advanced",
            default_config={
                "temperature": 0.7,
                "model": "gpt-4",
                "advanced": {"retries": 3, "timeout": 30},
            },
        )

        override = {
            "advanced": {"retries": 5},  # Partial override
            "new_field": "new_value",
        }

        merged = AgentConfigService.merge_config(agent_type, override)

        # dict.update() replaces whole "advanced" dict
        assert merged["advanced"] == {"retries": 5}
        assert merged["new_field"] == "new_value"
        assert merged["temperature"] == 0.7

    def test_extract_profile_details_preserves_list_types(self):
        """Test that capabilities and examples are preserved as lists."""
        agent_type = AgentTypeConfig(
            slug="test",
            name="Test",
            default_config={
                "profile": {
                    "capabilities": ["cap1", "cap2"],
                    "sample_prompts": ["prompt1"],
                }
            },
        )

        profile = AgentConfigService.extract_profile_details(agent_type)

        assert isinstance(profile.capabilities, list)
        assert isinstance(profile.examples, list)
