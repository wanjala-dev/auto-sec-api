"""Unit tests for AgentEntity and AgentProfileEntity."""

from datetime import datetime
from uuid import UUID, uuid4

from components.agents.domain.entities.agent_entity import (
    AgentEntity,
    AgentProfileEntity,
)


class TestAgentEntity:
    """Tests for AgentEntity — the core agent aggregate root."""

    def test_create_minimal_agent(self):
        """Test creating an agent with minimal required fields."""
        agent_id = uuid4()
        user_id = uuid4()

        agent = AgentEntity(
            agent_id=agent_id,
            agent_type="budget_analyst",
            user_id=user_id,
            status="active",
        )

        assert agent.agent_id == agent_id
        assert agent.agent_type == "budget_analyst"
        assert agent.user_id == user_id
        assert agent.status == "active"
        assert agent.config == {}
        assert agent.workspace_id is None
        assert agent.department_id is None
        assert agent.last_query == ""
        assert agent.last_result == ""
        assert agent.execution_count == 0
        assert agent.created_at is None
        assert agent.updated_at is None
        assert agent.last_executed is None

    def test_create_agent_with_all_fields(self):
        """Test creating an agent with all fields populated."""
        agent_id = uuid4()
        user_id = uuid4()
        workspace_id = uuid4()
        department_id = uuid4()
        now = datetime.utcnow()
        config = {"temperature": 0.7, "max_tokens": 500}

        agent = AgentEntity(
            agent_id=agent_id,
            agent_type="newsletter_creator",
            user_id=user_id,
            status="paused",
            config=config,
            workspace_id=workspace_id,
            department_id=department_id,
            last_query="How to optimize campaigns?",
            last_result="Here are optimization strategies...",
            execution_count=42,
            created_at=now,
            updated_at=now,
            last_executed=now,
        )

        assert agent.agent_id == agent_id
        assert agent.agent_type == "newsletter_creator"
        assert agent.user_id == user_id
        assert agent.status == "paused"
        assert agent.config == config
        assert agent.workspace_id == workspace_id
        assert agent.department_id == department_id
        assert agent.last_query == "How to optimize campaigns?"
        assert agent.last_result == "Here are optimization strategies..."
        assert agent.execution_count == 42
        assert agent.created_at == now
        assert agent.updated_at == now
        assert agent.last_executed == now

    def test_agent_is_frozen(self):
        """Test that AgentEntity is immutable (frozen dataclass)."""
        agent = AgentEntity(
            agent_id=uuid4(),
            agent_type="budget_analyst",
            user_id=uuid4(),
            status="active",
        )

        try:
            agent.execution_count = 99
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected

    def test_agent_with_empty_config_dict(self):
        """Test that empty config defaults to empty dict."""
        agent = AgentEntity(
            agent_id=uuid4(),
            agent_type="teammate",
            user_id=uuid4(),
            status="active",
        )

        assert agent.config == {}
        assert isinstance(agent.config, dict)

    def test_agent_with_complex_config(self):
        """Test agent with nested config structures."""
        config = {
            "profile": {
                "summary": "Analyzes budgets",
                "capabilities": ["forecasting", "optimization"],
            },
            "run_config": {
                "temperature": 0.5,
                "top_p": 0.9,
                "max_tokens": 1000,
            },
            "allowed_tools": ["list_budgets", "create_budget"],
        }

        agent = AgentEntity(
            agent_id=uuid4(),
            agent_type="budget_analyst",
            user_id=uuid4(),
            status="active",
            config=config,
        )

        assert agent.config == config
        assert agent.config["profile"]["summary"] == "Analyzes budgets"
        assert agent.config["run_config"]["max_tokens"] == 1000


class TestAgentProfileEntity:
    """Tests for AgentProfileEntity — the social/visibility layer."""

    def test_create_minimal_profile(self):
        """Test creating a profile with required fields."""
        agent_id = uuid4()

        profile = AgentProfileEntity(
            agent_id=agent_id,
            display_name="Budget Analyst",
            summary="Analyzes and forecasts budgets",
            avatar_url="https://example.com/avatar.png",
        )

        assert profile.agent_id == agent_id
        assert profile.display_name == "Budget Analyst"
        assert profile.summary == "Analyzes and forecasts budgets"
        assert profile.avatar_url == "https://example.com/avatar.png"
        assert profile.tags == []
        assert profile.visibility == "workspace_only"
        assert profile.allow_followers is True
        assert profile.allow_ratings is True
        assert profile.allow_comments is True
        assert profile.is_disabled is False
        assert profile.created_at is None
        assert profile.updated_at is None

    def test_create_profile_with_all_fields(self):
        """Test creating a profile with all fields populated."""
        agent_id = uuid4()
        now = datetime.utcnow()
        tags = ["budget", "finance", "forecasting"]

        profile = AgentProfileEntity(
            agent_id=agent_id,
            display_name="CFO Assistant",
            summary="Advanced budget and financial analysis",
            avatar_url="https://cdn.example.com/avatars/cfo.png",
            tags=tags,
            visibility="shared_link",
            allow_followers=False,
            allow_ratings=False,
            allow_comments=True,
            is_disabled=True,
            created_at=now,
            updated_at=now,
        )

        assert profile.agent_id == agent_id
        assert profile.display_name == "CFO Assistant"
        assert profile.summary == "Advanced budget and financial analysis"
        assert profile.avatar_url == "https://cdn.example.com/avatars/cfo.png"
        assert profile.tags == tags
        assert profile.visibility == "shared_link"
        assert profile.allow_followers is False
        assert profile.allow_ratings is False
        assert profile.allow_comments is True
        assert profile.is_disabled is True
        assert profile.created_at == now
        assert profile.updated_at == now

    def test_profile_is_frozen(self):
        """Test that AgentProfileEntity is immutable."""
        profile = AgentProfileEntity(
            agent_id=uuid4(),
            display_name="Test Agent",
            summary="Test",
            avatar_url="http://example.com/avatar.png",
        )

        try:
            profile.is_disabled = True
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected

    def test_profile_with_multiple_tags(self):
        """Test profile with multiple tags."""
        tags = ["workflow", "automation", "ai", "budget", "reporting"]

        profile = AgentProfileEntity(
            agent_id=uuid4(),
            display_name="Multi-Tool Agent",
            summary="Handles multiple domains",
            avatar_url="http://example.com/multi.png",
            tags=tags,
        )

        assert profile.tags == tags
        assert len(profile.tags) == 5
        assert "automation" in profile.tags

    def test_profile_with_different_visibilities(self):
        """Test profiles with different visibility settings."""
        profile_workspace_only = AgentProfileEntity(
            agent_id=uuid4(),
            display_name="Private Agent",
            summary="For workspace only",
            avatar_url="http://example.com/private.png",
            visibility="workspace_only",
        )

        profile_shared = AgentProfileEntity(
            agent_id=uuid4(),
            display_name="Shared Agent",
            summary="For shared link",
            avatar_url="http://example.com/shared.png",
            visibility="shared_link",
        )

        assert profile_workspace_only.visibility == "workspace_only"
        assert profile_shared.visibility == "shared_link"

    def test_profile_social_settings_combinations(self):
        """Test different social feature combinations."""
        # Public: all social features enabled
        public_profile = AgentProfileEntity(
            agent_id=uuid4(),
            display_name="Public Agent",
            summary="Everyone can interact",
            avatar_url="http://example.com/public.png",
            allow_followers=True,
            allow_ratings=True,
            allow_comments=True,
        )

        assert public_profile.allow_followers is True
        assert public_profile.allow_ratings is True
        assert public_profile.allow_comments is True

        # Restricted: only comments disabled
        restricted_profile = AgentProfileEntity(
            agent_id=uuid4(),
            display_name="Restricted Agent",
            summary="Limited interaction",
            avatar_url="http://example.com/restricted.png",
            allow_followers=True,
            allow_ratings=True,
            allow_comments=False,
        )

        assert restricted_profile.allow_followers is True
        assert restricted_profile.allow_ratings is True
        assert restricted_profile.allow_comments is False

    def test_disabled_profile(self):
        """Test a disabled profile."""
        profile = AgentProfileEntity(
            agent_id=uuid4(),
            display_name="Disabled Agent",
            summary="This agent is disabled",
            avatar_url="http://example.com/disabled.png",
            is_disabled=True,
        )

        assert profile.is_disabled is True

    def test_profile_timestamps(self):
        """Test profile creation and update timestamps."""
        created_at = datetime(2025, 1, 1, 12, 0, 0)
        updated_at = datetime(2025, 1, 15, 14, 30, 0)

        profile = AgentProfileEntity(
            agent_id=uuid4(),
            display_name="Timestamped Agent",
            summary="Has timestamps",
            avatar_url="http://example.com/timestamped.png",
            created_at=created_at,
            updated_at=updated_at,
        )

        assert profile.created_at == created_at
        assert profile.updated_at == updated_at
        assert profile.updated_at > profile.created_at
