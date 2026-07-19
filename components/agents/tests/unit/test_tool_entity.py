"""Unit tests for ToolEntity, ToolPermission, and ToolSchema."""

from datetime import datetime
from uuid import uuid4

from components.agents.domain.entities.tool_entity import (
    ToolEntity,
    ToolPermission,
    ToolSchema,
)
from components.agents.domain.enums import ModelTier, ToolAccessStrategy, ToolStatus


class TestToolPermission:
    """Tests for ToolPermission — access control for tools."""

    def test_create_permission_minimal(self):
        """Test creating a permission with minimal fields."""
        perm = ToolPermission(action="budget:read")

        assert perm.action == "budget:read"
        assert perm.scope_type == "workspace"
        assert perm.description == ""

    def test_create_permission_with_all_fields(self):
        """Test creating a permission with all fields."""
        perm = ToolPermission(
            action="budget:write",
            scope_type="department",
            description="Allows writing budget data within department",
        )

        assert perm.action == "budget:write"
        assert perm.scope_type == "department"
        assert perm.description == "Allows writing budget data within department"

    def test_permission_is_frozen(self):
        """Test that ToolPermission is immutable."""
        perm = ToolPermission(action="task:read")

        try:
            perm.action = "task:write"
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected

    def test_permission_wildcard_actions(self):
        """Test wildcard permission actions."""
        wildcard_perm = ToolPermission(action="budget:*")
        global_wildcard = ToolPermission(action="*")

        assert wildcard_perm.action == "budget:*"
        assert global_wildcard.action == "*"


class TestToolSchema:
    """Tests for ToolSchema — input/output definitions."""

    def test_create_minimal_schema(self):
        """Test creating a schema with minimal fields."""
        schema = ToolSchema()

        assert schema.input_fields == {}
        assert schema.output_fields == {}
        assert schema.description == ""

    def test_create_schema_with_fields(self):
        """Test creating a schema with field definitions."""
        input_fields = {
            "budget_id": {"type": "string", "required": True},
            "year": {"type": "integer", "required": False},
        }
        output_fields = {
            "amount": {"type": "number"},
            "currency": {"type": "string"},
        }

        schema = ToolSchema(
            input_fields=input_fields,
            output_fields=output_fields,
            description="Lists budgets for a given year",
        )

        assert schema.input_fields == input_fields
        assert schema.output_fields == output_fields
        assert schema.description == "Lists budgets for a given year"

    def test_schema_is_frozen(self):
        """Test that ToolSchema is immutable."""
        schema = ToolSchema(
            input_fields={"id": {"type": "string"}},
        )

        try:
            schema.input_fields["id"]["type"] = "integer"
            # Note: dict inside frozen dataclass is still mutable
            # But reassigning the field is not allowed
            schema.description = "modified"
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected


class TestToolEntity:
    """Tests for ToolEntity — aggregate root for tools."""

    def test_create_tool_minimal(self):
        """Test creating a tool with minimal required fields."""
        tool_id = uuid4()

        tool = ToolEntity(
            tool_id=tool_id,
            slug="list_budgets",
            name="List Budgets",
            description="Lists all available budgets",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="budget_analyst",
        )

        assert tool.tool_id == tool_id
        assert tool.slug == "list_budgets"
        assert tool.name == "List Budgets"
        assert tool.description == "Lists all available budgets"
        assert tool.access_strategy == ToolAccessStrategy.ORM
        assert tool.agent_type == "budget_analyst"
        assert tool.status == ToolStatus.ACTIVE
        assert tool.config == {}
        assert tool.required_permissions == []
        assert tool.tags == []
        assert tool.workspace_id is None
        assert tool.model_tier == ModelTier.TIER_2
        assert tool.cacheable is True
        assert tool.cache_ttl_seconds == 300
        assert tool.require_llm is False
        assert tool.max_batch_size == 10

    def test_create_tool_with_all_fields(self):
        """Test creating a tool with all fields populated."""
        tool_id = uuid4()
        workspace_id = uuid4()
        now = datetime.utcnow()
        permissions = [
            ToolPermission(action="budget:read"),
            ToolPermission(action="budget:write"),
        ]
        config = {"timeout": 30, "retry_count": 3}
        schema = ToolSchema(
            input_fields={"budget_id": {"type": "string"}},
            output_fields={"amount": {"type": "number"}},
        )

        tool = ToolEntity(
            tool_id=tool_id,
            slug="create_budget",
            name="Create Budget",
            description="Creates a new budget",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="budget_analyst",
            status=ToolStatus.ACTIVE,
            config=config,
            schema=schema,
            required_permissions=permissions,
            tags=["budget", "write"],
            access_config={"model_paths": ["infrastructure.persistence.budget.models.Budget"]},
            model_tier=ModelTier.TIER_1,
            cacheable=False,
            cache_ttl_seconds=0,
            require_llm=True,
            max_batch_size=5,
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
        )

        assert tool.tool_id == tool_id
        assert tool.slug == "create_budget"
        assert tool.agent_type == "budget_analyst"
        assert tool.status == ToolStatus.ACTIVE
        assert tool.config == config
        assert tool.schema == schema
        assert tool.required_permissions == permissions
        assert tool.tags == ["budget", "write"]
        assert tool.model_tier == ModelTier.TIER_1
        assert tool.cacheable is False
        assert tool.cache_ttl_seconds == 0
        assert tool.require_llm is True
        assert tool.max_batch_size == 5
        assert tool.workspace_id == workspace_id
        assert tool.created_at == now
        assert tool.updated_at == now

    def test_tool_factory_create(self):
        """Test ToolEntity.create() factory method."""
        tool = ToolEntity.create(
            slug="list_tasks",
            name="List Tasks",
            description="Lists all tasks",
            access_strategy=ToolAccessStrategy.WEB,
            agent_type="task_runner",
        )

        assert tool.tool_id is not None
        assert tool.slug == "list_tasks"
        assert tool.name == "List Tasks"
        assert tool.access_strategy == ToolAccessStrategy.WEB
        assert tool.created_at is not None
        assert tool.updated_at is not None
        assert tool.created_at == tool.updated_at

    def test_tool_factory_create_with_permissions(self):
        """Test ToolEntity.create() with permissions."""
        permissions = [
            ToolPermission(action="task:read"),
            ToolPermission(action="task:write"),
        ]

        tool = ToolEntity.create(
            slug="create_task",
            name="Create Task",
            description="Creates a new task",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="task_runner",
            required_permissions=permissions,
        )

        assert tool.required_permissions == permissions
        assert len(tool.required_permissions) == 2

    def test_tool_factory_rehydrate(self):
        """Test ToolEntity.rehydrate() factory method."""
        tool_id = uuid4()
        now = datetime.utcnow()

        tool = ToolEntity.rehydrate(
            tool_id=tool_id,
            slug="archived_tool",
            name="Archived",
            description="An archived tool",
            access_strategy=ToolAccessStrategy.FILE,
            agent_type="legacy",
            status=ToolStatus.DEPRECATED,
            created_at=now,
            updated_at=now,
        )

        assert tool.tool_id == tool_id
        assert tool.slug == "archived_tool"
        assert tool.status == ToolStatus.DEPRECATED

    def test_tool_is_active_property(self):
        """Test is_active property."""
        active = ToolEntity(
            tool_id=uuid4(),
            slug="active",
            name="Active",
            description="Active tool",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            status=ToolStatus.ACTIVE,
        )

        disabled = ToolEntity(
            tool_id=uuid4(),
            slug="disabled",
            name="Disabled",
            description="Disabled tool",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            status=ToolStatus.DISABLED,
        )

        assert active.is_active is True
        assert disabled.is_active is False

    def test_tool_access_strategy_properties(self):
        """Test access strategy detection properties."""
        orm_tool = ToolEntity(
            tool_id=uuid4(),
            slug="orm",
            name="ORM Tool",
            description="Uses ORM",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
        )

        mcp_tool = ToolEntity(
            tool_id=uuid4(),
            slug="mcp",
            name="MCP Tool",
            description="Uses MCP",
            access_strategy=ToolAccessStrategy.MCP,
            agent_type="test",
        )

        web_tool = ToolEntity(
            tool_id=uuid4(),
            slug="web",
            name="Web Tool",
            description="Uses Web",
            access_strategy=ToolAccessStrategy.WEB,
            agent_type="test",
        )

        file_tool = ToolEntity(
            tool_id=uuid4(),
            slug="file",
            name="File Tool",
            description="Uses File",
            access_strategy=ToolAccessStrategy.FILE,
            agent_type="test",
        )

        assert orm_tool.is_orm_tool is True
        assert mcp_tool.is_mcp_tool is True
        assert web_tool.is_web_tool is True
        assert file_tool.is_file_tool is True

    def test_tool_requires_permission(self):
        """Test requires_permission() method."""
        tool_with_perms = ToolEntity(
            tool_id=uuid4(),
            slug="secure",
            name="Secure Tool",
            description="Requires permissions",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            required_permissions=[
                ToolPermission(action="budget:read"),
                ToolPermission(action="task:write"),
            ],
        )

        tool_without_perms = ToolEntity(
            tool_id=uuid4(),
            slug="public",
            name="Public Tool",
            description="No permissions",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
        )

        assert tool_with_perms.requires_permission("budget:read") is True
        assert tool_with_perms.requires_permission("task:write") is True
        assert tool_with_perms.requires_permission("other:read") is False
        assert tool_without_perms.requires_permission("anything") is False

    def test_tool_requires_permission_wildcard(self):
        """Test permission checks with wildcard."""
        tool = ToolEntity(
            tool_id=uuid4(),
            slug="budget_tool",
            name="Budget Tool",
            description="Budget operations",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            required_permissions=[
                ToolPermission(action="budget:*"),
            ],
        )

        assert tool.requires_permission("budget:read") is True
        assert tool.requires_permission("budget:write") is True
        assert tool.requires_permission("budget:anything") is True

    def test_tool_check_permissions_all_granted(self):
        """Test check_permissions() when all are granted."""
        tool = ToolEntity(
            tool_id=uuid4(),
            slug="restricted",
            name="Restricted",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            required_permissions=[
                ToolPermission(action="budget:read"),
                ToolPermission(action="task:write"),
            ],
        )

        granted = ["budget:read", "task:write", "other:read"]
        assert tool.check_permissions(granted) is True

    def test_tool_check_permissions_missing(self):
        """Test check_permissions() when some are missing."""
        tool = ToolEntity(
            tool_id=uuid4(),
            slug="restricted",
            name="Restricted",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            required_permissions=[
                ToolPermission(action="budget:read"),
                ToolPermission(action="task:write"),
            ],
        )

        granted = ["budget:read"]  # Missing task:write
        assert tool.check_permissions(granted) is False

    def test_tool_check_permissions_wildcard_domain(self):
        """Test check_permissions() with wildcard domain."""
        tool = ToolEntity(
            tool_id=uuid4(),
            slug="budget_tool",
            name="Budget Tool",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            required_permissions=[
                ToolPermission(action="budget:read"),
                ToolPermission(action="task:write"),
            ],
        )

        granted = ["budget:*", "other:read"]  # Wildcard covers budget:read
        assert tool.check_permissions(granted) is False  # Still missing task:write

    def test_tool_check_permissions_global_wildcard(self):
        """Test check_permissions() with global wildcard."""
        tool = ToolEntity(
            tool_id=uuid4(),
            slug="secure",
            name="Secure",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            required_permissions=[
                ToolPermission(action="budget:read"),
                ToolPermission(action="task:write"),
            ],
        )

        granted = ["*"]  # Global wildcard covers all
        assert tool.check_permissions(granted) is True

    def test_tool_is_cacheable(self):
        """Test is_cacheable property."""
        cacheable_active = ToolEntity(
            tool_id=uuid4(),
            slug="cacheable",
            name="Cacheable",
            description="Can cache",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            status=ToolStatus.ACTIVE,
            cacheable=True,
        )

        not_cacheable = ToolEntity(
            tool_id=uuid4(),
            slug="not_cacheable",
            name="Not Cacheable",
            description="Cannot cache",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            cacheable=False,
        )

        cacheable_disabled = ToolEntity(
            tool_id=uuid4(),
            slug="disabled_cache",
            name="Disabled",
            description="Disabled but cacheable",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            status=ToolStatus.DISABLED,
            cacheable=True,
        )

        assert cacheable_active.is_cacheable is True
        assert not_cacheable.is_cacheable is False
        assert cacheable_disabled.is_cacheable is False

    def test_tool_cost_multiplier(self):
        """Test cost_multiplier property."""
        tier1_tool = ToolEntity(
            tool_id=uuid4(),
            slug="cheap",
            name="Cheap",
            description="Low cost",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            model_tier=ModelTier.TIER_1,
        )

        tier2_tool = ToolEntity(
            tool_id=uuid4(),
            slug="medium",
            name="Medium",
            description="Medium cost",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            model_tier=ModelTier.TIER_2,
        )

        tier3_tool = ToolEntity(
            tool_id=uuid4(),
            slug="expensive",
            name="Expensive",
            description="High cost",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            model_tier=ModelTier.TIER_3,
        )

        assert tier1_tool.cost_multiplier == 1.0
        assert tier2_tool.cost_multiplier == 5.0
        assert tier3_tool.cost_multiplier == 20.0

    def test_tool_is_cheap_and_expensive_properties(self):
        """Test is_cheap_tool and is_expensive_tool properties."""
        cheap = ToolEntity(
            tool_id=uuid4(),
            slug="cheap",
            name="Cheap",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            model_tier=ModelTier.TIER_1,
        )

        expensive = ToolEntity(
            tool_id=uuid4(),
            slug="expensive",
            name="Expensive",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            model_tier=ModelTier.TIER_3,
        )

        assert cheap.is_cheap_tool is True
        assert cheap.is_expensive_tool is False
        assert expensive.is_cheap_tool is False
        assert expensive.is_expensive_tool is True

    def test_tool_supports_batching(self):
        """Test supports_batching() method."""
        active_batchable = ToolEntity(
            tool_id=uuid4(),
            slug="batch_orm",
            name="Batchable ORM",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            status=ToolStatus.ACTIVE,
            max_batch_size=10,
        )

        file_tool = ToolEntity(
            tool_id=uuid4(),
            slug="file_tool",
            name="File Tool",
            description="Test",
            access_strategy=ToolAccessStrategy.FILE,
            agent_type="test",
            max_batch_size=10,
        )

        inactive_tool = ToolEntity(
            tool_id=uuid4(),
            slug="inactive",
            name="Inactive",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            status=ToolStatus.DISABLED,
        )

        assert active_batchable.supports_batching() is True
        assert file_tool.supports_batching() is False
        assert inactive_tool.supports_batching() is False

    def test_tool_validate_batch_size(self):
        """Test validate_batch_size() method."""
        tool = ToolEntity(
            tool_id=uuid4(),
            slug="batch",
            name="Batch Tool",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            max_batch_size=10,
        )

        # Valid sizes
        tool.validate_batch_size(1)
        tool.validate_batch_size(5)
        tool.validate_batch_size(10)

        # Invalid size
        try:
            tool.validate_batch_size(11)
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "exceeds max_batch_size" in str(e)

    def test_tool_should_require_health_check(self):
        """Test should_require_health_check() method."""
        mcp_tool = ToolEntity(
            tool_id=uuid4(),
            slug="mcp",
            name="MCP Tool",
            description="Test",
            access_strategy=ToolAccessStrategy.MCP,
            agent_type="test",
        )

        web_tool = ToolEntity(
            tool_id=uuid4(),
            slug="web",
            name="Web Tool",
            description="Test",
            access_strategy=ToolAccessStrategy.WEB,
            agent_type="test",
        )

        orm_tool = ToolEntity(
            tool_id=uuid4(),
            slug="orm",
            name="ORM Tool",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
        )

        assert mcp_tool.should_require_health_check() is True
        assert web_tool.should_require_health_check() is True
        assert orm_tool.should_require_health_check() is False

    def test_tool_get_effective_config(self):
        """Test get_effective_config() method."""
        config = {"timeout": 30, "retries": 3}

        tool = ToolEntity(
            tool_id=uuid4(),
            slug="configured",
            name="Configured Tool",
            description="Test",
            access_strategy=ToolAccessStrategy.ORM,
            agent_type="test",
            config=config,
            model_tier=ModelTier.TIER_2,
            cacheable=True,
            cache_ttl_seconds=600,
            require_llm=False,
            max_batch_size=5,
        )

        effective = tool.get_effective_config()

        assert effective["timeout"] == 30
        assert effective["retries"] == 3
        assert effective["model_tier"] == ModelTier.TIER_2
        assert effective["cacheable"] is True
        assert effective["cache_ttl_seconds"] == 600
        assert effective["require_llm"] is False
        assert effective["max_batch_size"] == 5

    def test_tool_validate_slug_invalid(self):
        """Test _validate_slug() with invalid slugs."""
        invalid_slugs = [
            "",
            "   ",
            "tool name",  # spaces
            "tool.name",  # dots
            "tool/name",  # slashes
            "tool@name",  # special chars
        ]

        for slug in invalid_slugs:
            try:
                ToolEntity.create(
                    slug=slug,
                    name="Test",
                    description="Test",
                    access_strategy=ToolAccessStrategy.ORM,
                    agent_type="test",
                )
                assert False, f"Should reject slug: {slug!r}"
            except ValueError:
                pass  # Expected

    def test_tool_validate_slug_valid(self):
        """Test _validate_slug() with valid slugs."""
        valid_slugs = [
            "list_budgets",
            "create-budget",
            "budget_2025",
            "list-budgets-v2",
        ]

        for slug in valid_slugs:
            tool = ToolEntity.create(
                slug=slug,
                name="Test",
                description="Test",
                access_strategy=ToolAccessStrategy.ORM,
                agent_type="test",
            )
            assert tool.slug == slug

    def test_tool_validate_access_strategy_invalid(self):
        """Test _validate_access_strategy() with invalid strategies."""
        invalid_strategy = "invalid_strategy"

        try:
            ToolEntity.create(
                slug="test",
                name="Test",
                description="Test",
                access_strategy=invalid_strategy,
                agent_type="test",
            )
            assert False, "Should reject invalid access strategy"
        except ValueError as e:
            assert "Invalid access strategy" in str(e)

    def test_tool_validate_access_strategy_valid(self):
        """Test _validate_access_strategy() with valid strategies."""
        for strategy in [ToolAccessStrategy.ORM, ToolAccessStrategy.MCP,
                        ToolAccessStrategy.WEB, ToolAccessStrategy.FILE]:
            tool = ToolEntity.create(
                slug="test",
                name="Test",
                description="Test",
                access_strategy=strategy,
                agent_type="test",
            )
            assert tool.access_strategy == strategy
