"""Unit tests for workflow constants and TriggerDefinition value object."""

from __future__ import annotations

import pytest

from components.workflow.domain.constants import (
    EVENT_STATUSES,
    NODE_TYPES,
    RUN_STATUSES,
    SOURCE_TYPES,
    STEP_EVENT_TYPES,
    STEP_STATES,
    TARGET_TYPES,
    TRIGGER_CATALOG,
    WORKFLOW_STATUSES,
    TriggerDefinition,
)


class TestTriggerDefinitionValueObject:
    """Test suite for TriggerDefinition immutable dataclass."""

    def test_trigger_definition_creation_with_defaults(self):
        """Should create TriggerDefinition with default values."""
        trigger = TriggerDefinition(
            id="contact_added",
            source_type="directory",
            label="New contact added",
        )

        assert trigger.id == "contact_added"
        assert trigger.source_type == "directory"
        assert trigger.label == "New contact added"
        assert trigger.goal_ids == ()
        assert trigger.compatible_node_types == ("start",)

    def test_trigger_definition_creation_with_all_fields(self):
        """Should create TriggerDefinition with all fields specified."""
        goal_ids = ("campaign", "sponsorship", "event")
        compatible_types = ("start", "task")

        trigger = TriggerDefinition(
            id="custom_trigger",
            source_type="custom",
            label="Custom event",
            goal_ids=goal_ids,
            compatible_node_types=compatible_types,
        )

        assert trigger.id == "custom_trigger"
        assert trigger.source_type == "custom"
        assert trigger.label == "Custom event"
        assert trigger.goal_ids == goal_ids
        assert trigger.compatible_node_types == compatible_types

    def test_trigger_definition_is_immutable(self):
        """Should raise error when trying to modify fields."""
        trigger = TriggerDefinition(
            id="contact_added",
            source_type="directory",
            label="New contact added",
        )

        with pytest.raises(Exception):
            trigger.id = "different_id"

        with pytest.raises(Exception):
            trigger.label = "Different label"

        with pytest.raises(Exception):
            trigger.goal_ids = ("new_goal",)

    def test_trigger_definition_equality(self):
        """Should compare based on all fields."""
        t1 = TriggerDefinition(
            id="contact_added",
            source_type="directory",
            label="New contact added",
            goal_ids=("campaign",),
        )
        t2 = TriggerDefinition(
            id="contact_added",
            source_type="directory",
            label="New contact added",
            goal_ids=("campaign",),
        )

        assert t1 == t2

    def test_trigger_definition_inequality_on_id(self):
        """Should be unequal when id differs."""
        t1 = TriggerDefinition(
            id="trigger_1",
            source_type="directory",
            label="Trigger 1",
        )
        t2 = TriggerDefinition(
            id="trigger_2",
            source_type="directory",
            label="Trigger 1",
        )

        assert t1 != t2

    def test_trigger_definition_inequality_on_goal_ids(self):
        """Should be unequal when goal_ids differ."""
        t1 = TriggerDefinition(
            id="contact_added",
            source_type="directory",
            label="New contact added",
            goal_ids=("campaign", "sponsorship"),
        )
        t2 = TriggerDefinition(
            id="contact_added",
            source_type="directory",
            label="New contact added",
            goal_ids=("campaign",),
        )

        assert t1 != t2

    def test_trigger_definition_with_empty_goal_ids(self):
        """Should accept empty tuple for goal_ids."""
        trigger = TriggerDefinition(
            id="generic_trigger",
            source_type="system",
            label="Generic trigger",
            goal_ids=(),
        )

        assert trigger.goal_ids == ()
        assert len(trigger.goal_ids) == 0

    def test_trigger_definition_with_single_goal(self):
        """Should accept single goal in goal_ids."""
        trigger = TriggerDefinition(
            id="task_completed",
            source_type="task",
            label="Task completed",
            goal_ids=("campaign",),
        )

        assert len(trigger.goal_ids) == 1
        assert "campaign" in trigger.goal_ids

    def test_trigger_definition_goal_ids_is_tuple(self):
        """Should ensure goal_ids is a tuple."""
        trigger = TriggerDefinition(
            id="contact_added",
            source_type="directory",
            label="New contact added",
            goal_ids=("campaign", "sponsorship", "event"),
        )

        assert isinstance(trigger.goal_ids, tuple)

    def test_trigger_definition_compatible_node_types_default(self):
        """Should default compatible_node_types to ('start',)."""
        trigger = TriggerDefinition(
            id="contact_added",
            source_type="directory",
            label="New contact added",
        )

        assert trigger.compatible_node_types == ("start",)

    def test_trigger_definition_compatible_node_types_custom(self):
        """Should allow custom compatible_node_types."""
        trigger = TriggerDefinition(
            id="custom",
            source_type="custom",
            label="Custom trigger",
            compatible_node_types=("start", "task", "webhook"),
        )

        assert trigger.compatible_node_types == ("start", "task", "webhook")


class TestWorkflowConstants:
    """Tests for workflow constant values."""

    def test_source_types_not_empty(self):
        """SOURCE_TYPES should contain valid source types."""
        assert len(SOURCE_TYPES) > 0
        assert "directory" in SOURCE_TYPES
        assert "task" in SOURCE_TYPES
        assert "event" in SOURCE_TYPES

    def test_source_types_are_strings(self):
        """All SOURCE_TYPES should be strings."""
        for source_type in SOURCE_TYPES:
            assert isinstance(source_type, str)
            assert len(source_type) > 0

    def test_target_types_contains_expected_values(self):
        """TARGET_TYPES should contain contact and group."""
        assert "contact" in TARGET_TYPES
        assert "group" in TARGET_TYPES
        assert len(TARGET_TYPES) == 2

    def test_node_types_contains_all_expected_nodes(self):
        """NODE_TYPES should contain all expected node types."""
        expected_types = ["start", "end", "message", "data_request", "decision", "task", "ai", "assign", "wait", "webhook"]

        for expected_type in expected_types:
            assert expected_type in NODE_TYPES

    def test_node_types_are_strings(self):
        """All NODE_TYPES should be strings."""
        for node_type in NODE_TYPES:
            assert isinstance(node_type, str)
            assert len(node_type) > 0

    def test_workflow_statuses_contains_expected_values(self):
        """WORKFLOW_STATUSES should contain all expected statuses."""
        expected = ["draft", "published", "paused", "archived"]

        for status in expected:
            assert status in WORKFLOW_STATUSES

    def test_run_statuses_contains_expected_values(self):
        """RUN_STATUSES should contain all expected run statuses."""
        expected = ["queued", "running", "paused", "completed", "failed", "canceled"]

        for status in expected:
            assert status in RUN_STATUSES

    def test_step_event_types_contains_expected_values(self):
        """STEP_EVENT_TYPES should contain all expected event types."""
        expected = ["entered", "completed", "failed", "branched"]

        for event_type in expected:
            assert event_type in STEP_EVENT_TYPES

    def test_step_states_contains_expected_values(self):
        """STEP_STATES should contain all expected step states."""
        expected = ["pending", "running", "waiting", "waiting_input", "completed", "failed"]

        for state in expected:
            assert state in STEP_STATES

    def test_event_statuses_contains_expected_values(self):
        """EVENT_STATUSES should contain all expected event statuses."""
        expected = ["pending", "processing", "processed", "failed"]

        for status in expected:
            assert status in EVENT_STATUSES

    def test_trigger_catalog_not_empty(self):
        """TRIGGER_CATALOG should contain trigger definitions."""
        assert len(TRIGGER_CATALOG) > 0

    def test_all_catalog_triggers_are_trigger_definitions(self):
        """All items in TRIGGER_CATALOG should be TriggerDefinition instances."""
        for trigger in TRIGGER_CATALOG:
            assert isinstance(trigger, TriggerDefinition)

    def test_all_catalog_trigger_ids_are_unique(self):
        """All trigger IDs in catalog should be unique."""
        ids = [t.id for t in TRIGGER_CATALOG]
        assert len(ids) == len(set(ids))

    def test_all_catalog_source_types_are_valid(self):
        """All catalog trigger source_types should be in SOURCE_TYPES."""
        for trigger in TRIGGER_CATALOG:
            assert trigger.source_type in SOURCE_TYPES

    def test_all_catalog_goal_ids_are_strings(self):
        """All goal IDs in catalog should be valid goal type strings."""
        valid_goal_types = {"campaign", "sponsorship", "event", "task", "project", "agents"}

        for trigger in TRIGGER_CATALOG:
            for goal_id in trigger.goal_ids:
                assert goal_id in valid_goal_types

    def test_trigger_catalog_contact_added_trigger(self):
        """Should have contact_added trigger in catalog."""
        contact_added = next((t for t in TRIGGER_CATALOG if t.id == "contact_added"), None)

        assert contact_added is not None
        assert contact_added.source_type == "directory"
        assert "campaign" in contact_added.goal_ids

    def test_trigger_catalog_task_completed_trigger(self):
        """Should have task_completed trigger in catalog."""
        task_completed = next((t for t in TRIGGER_CATALOG if t.id == "task_completed"), None)

        assert task_completed is not None
        assert task_completed.source_type == "task"
        assert "campaign" in task_completed.goal_ids
        assert "sponsorship" in task_completed.goal_ids

    def test_trigger_catalog_donation_received_trigger(self):
        """Should have donation_received trigger in catalog."""
        donation = next((t for t in TRIGGER_CATALOG if t.id == "donation_received"), None)

        assert donation is not None
        assert donation.source_type == "sponsorship"
        assert "sponsorship" in donation.goal_ids

    def test_all_catalog_triggers_have_default_compatible_nodes(self):
        """All catalog triggers should have 'start' as compatible node type."""
        for trigger in TRIGGER_CATALOG:
            # Default is ('start',), should allow start nodes
            assert "start" in trigger.compatible_node_types

    def test_workflow_status_values_are_mutually_exclusive(self):
        """Workflow statuses should be distinct."""
        assert len(WORKFLOW_STATUSES) == len(set(WORKFLOW_STATUSES))

    def test_run_status_values_are_mutually_exclusive(self):
        """Run statuses should be distinct."""
        assert len(RUN_STATUSES) == len(set(RUN_STATUSES))

    def test_step_state_values_are_mutually_exclusive(self):
        """Step states should be distinct."""
        assert len(STEP_STATES) == len(set(STEP_STATES))

    def test_event_status_values_are_mutually_exclusive(self):
        """Event statuses should be distinct."""
        assert len(EVENT_STATUSES) == len(set(EVENT_STATUSES))

    def test_node_types_are_lowercase(self):
        """All node types should be lowercase."""
        for node_type in NODE_TYPES:
            assert node_type == node_type.lower()

    def test_workflow_statuses_are_lowercase(self):
        """All workflow statuses should be lowercase."""
        for status in WORKFLOW_STATUSES:
            assert status == status.lower()

    def test_run_statuses_are_lowercase(self):
        """All run statuses should be lowercase."""
        for status in RUN_STATUSES:
            assert status == status.lower()

    def test_trigger_ids_are_snake_case(self):
        """All trigger IDs should be snake_case."""
        for trigger in TRIGGER_CATALOG:
            assert "_" in trigger.id or trigger.id.islower()
            # Should not contain hyphens or spaces
            assert "-" not in trigger.id

    def test_source_types_coverage_in_catalog(self):
        """All source types should have at least one trigger in catalog."""
        catalog_source_types = {t.source_type for t in TRIGGER_CATALOG}

        assert "directory" in catalog_source_types
        assert "task" in catalog_source_types
        assert "event" in catalog_source_types


class TestTriggerDefinitionIntegration:
    """Integration tests for TriggerDefinition with constants."""

    def test_trigger_goal_ids_match_known_goal_types(self):
        """All trigger goal IDs should be valid goal types."""
        valid_goals = {"campaign", "event", "sponsorship", "task", "project", "agents"}

        for trigger in TRIGGER_CATALOG:
            for goal_id in trigger.goal_ids:
                assert goal_id in valid_goals

    def test_trigger_source_type_matches_constant(self):
        """Trigger source_type should match SOURCE_TYPES constant."""
        for trigger in TRIGGER_CATALOG:
            assert trigger.source_type in SOURCE_TYPES

    def test_can_construct_custom_trigger(self):
        """Should be able to create custom trigger definitions."""
        custom = TriggerDefinition(
            id="custom_event",
            source_type="directory",
            label="Custom directory event",
            goal_ids=("campaign",),
            compatible_node_types=("start", "task"),
        )

        assert custom.id == "custom_event"
        assert custom.source_type in SOURCE_TYPES
        assert custom.goal_ids == ("campaign",)
