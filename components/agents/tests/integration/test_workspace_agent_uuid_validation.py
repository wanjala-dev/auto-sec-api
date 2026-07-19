"""Regression tests for the LLM-string-as-UUID hallucination cascade.

Background — incident on 2026-05-08. Henry asked the agent "how many
tasks are in progress?" and got back fabricated content claiming
"one task that was in progress but failed with the error message
''None' is not a valid UUID'. This task was associated with the
execution ID '15'."

Trace:

1. The deep-agent planner routed to the wrong worker
   (``workspace_agent.get_organization_operations``) because the
   question wasn't disambiguated.
2. The LLM passed the literal string ``"None"`` as ``organization_id``.
3. ``_resolve_org_id`` treated the truthy ``"None"`` string as a
   real id, skipping the workspace fallback.
4. ``Workspace.objects.get(id="None")`` raised
   ``ValidationError: "'None' is not a valid UUID"``.
5. The traceback bubbled up as the tool's response text.
6. The LLM read its own crash message and narrated it back to the
   user as if it were data about workspace tasks.

Tests below pin every link in that chain so a future revert fails
loudly here instead of silently leaking a tool-error string into
the user's chat.
"""
from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.tools.workspace_agent import (
    _coerce_uuid,
    _fetch_workspace,
    _is_nullish,
    _resolve_org_id,
    get_organization_operations,
    update_organization,
)


@pytest.mark.unit
class TestIsNullish:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "  ",
            "None",
            "none",
            "NONE",
            "null",
            "NULL",
            "undefined",
            "nil",
            "  None  ",
        ],
    )
    def test_returns_true_for_llm_placeholder_strings(self, value):
        assert _is_nullish(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "any-real-string",
            "038d31c8-4564-4db1-a0d7-359509ffa99f",
            42,
            False,  # 'False' is its own thing — only nullish-like strings count
            0,
        ],
    )
    def test_returns_false_for_real_values(self, value):
        assert _is_nullish(value) is False


@pytest.mark.unit
class TestCoerceUuid:
    def test_returns_normalised_string_for_valid_uuid(self):
        result = _coerce_uuid("038d31c8-4564-4db1-a0d7-359509ffa99f")
        assert result == "038d31c8-4564-4db1-a0d7-359509ffa99f"

    def test_returns_none_for_llm_placeholder_strings(self):
        # The exact bug from prod: LLM passed "None" as a UUID.
        # Caller must see None and fall back to the agent's workspace.
        assert _coerce_uuid("None") is None
        assert _coerce_uuid("null") is None
        assert _coerce_uuid("undefined") is None
        assert _coerce_uuid("") is None
        assert _coerce_uuid(None) is None

    def test_returns_none_for_garbage_strings(self):
        assert _coerce_uuid("not a uuid") is None
        assert _coerce_uuid("12345") is None
        assert _coerce_uuid("workspace-name") is None


class _StubAgent:
    """Tiny stand-in for the BaseAgent surface ``_resolve_org_id`` reads."""

    def __init__(self, workspace_id=None):
        self.workspace_id = workspace_id


@pytest.mark.unit
class TestResolveOrgId:
    """The exact incident path. Each test pins a regression scenario."""

    def test_falls_back_to_agent_workspace_when_data_says_None(self):
        # The bug: pre-fix, ``_resolve_org_id({"organization_id": "None"}, ...)``
        # returned ``"None"`` instead of the agent's workspace_id, and the
        # tool then handed that to ``Workspace.objects.get(id="None")``.
        agent = _StubAgent(workspace_id="038d31c8-4564-4db1-a0d7-359509ffa99f")
        result = _resolve_org_id({"organization_id": "None"}, agent)
        assert result == "038d31c8-4564-4db1-a0d7-359509ffa99f"

    def test_falls_back_for_null_undefined_and_empty(self):
        agent = _StubAgent(workspace_id="038d31c8-4564-4db1-a0d7-359509ffa99f")
        for placeholder in ("null", "undefined", ""):
            assert (
                _resolve_org_id({"organization_id": placeholder}, agent)
                == "038d31c8-4564-4db1-a0d7-359509ffa99f"
            )

    def test_explicit_valid_uuid_wins_over_agent_workspace(self):
        agent = _StubAgent(workspace_id="038d31c8-4564-4db1-a0d7-359509ffa99f")
        explicit = "1bb1bbbb-cccc-dddd-eeee-ffffffffffff"
        assert _resolve_org_id({"organization_id": explicit}, agent) == explicit

    def test_returns_none_when_no_valid_id_anywhere(self):
        # Garbage in payload, no agent fallback → caller sees None and
        # returns "Organization identifier is required" instead of
        # crashing on a malformed UUID.
        agent = _StubAgent(workspace_id=None)
        assert _resolve_org_id({"organization_id": "None"}, agent) is None

    def test_workspace_id_key_resolves_too(self):
        agent = _StubAgent()
        assert (
            _resolve_org_id(
                {"workspace_id": "038d31c8-4564-4db1-a0d7-359509ffa99f"}, agent
            )
            == "038d31c8-4564-4db1-a0d7-359509ffa99f"
        )


@pytest.mark.django_db
class TestFetchWorkspace:
    def test_returns_workspace_when_id_is_valid_and_exists(self, workspace_factory):
        ws = workspace_factory()
        result, error = _fetch_workspace(str(ws.id))
        assert error is None
        assert result is not None
        assert str(result.id) == str(ws.id)

    def test_returns_clean_error_for_nonexistent_uuid(self):
        # Valid UUID format, but no row. Pre-fix behaviour: bubbled
        # Workspace.DoesNotExist as a 500 the LLM would narrate.
        bogus = "deadbeef-dead-beef-dead-beefdeadbeef"
        result, error = _fetch_workspace(bogus)
        assert result is None
        assert error == f"No organization found with id {bogus}."

    def test_returns_clean_error_for_malformed_uuid_string(self):
        # Defence in depth: even if a caller bypasses _resolve_org_id
        # and hands us ``"None"``, the wrapper catches the
        # ValidationError and returns a flat string.
        result, error = _fetch_workspace("None")
        assert result is None
        assert "malformed" in error.lower() or "uuid" in error.lower()


@pytest.mark.django_db
class TestGetOrganizationOperationsRegression:
    """The exact prod call site. Pre-fix, this raised
    ``ValidationError: "'None' is not a valid UUID"`` which the LLM
    then narrated back to the user as if it described real data.
    """

    def test_with_None_string_falls_back_to_agent_workspace_no_crash(
        self, workspace_factory
    ):
        ws = workspace_factory()
        agent = _StubAgent(workspace_id=str(ws.id))
        # The LLM call shape from prod — argument is the literal "None".
        result = get_organization_operations(agent, organization_id="None")
        # Assert no traceback leaked. The string "is not a valid UUID"
        # was the hallucination trigger; it must not appear in the
        # response anymore.
        assert "is not a valid UUID" not in result
        # Either we got a real Operations listing or a clean
        # "No operations found" message — both are acceptable
        # grounded responses.
        assert (
            "Organization Operations" in result
            or "No operations found" in result
        )

    def test_with_no_argument_uses_agent_workspace(self, workspace_factory):
        ws = workspace_factory()
        agent = _StubAgent(workspace_id=str(ws.id))
        result = get_organization_operations(agent)
        assert "is not a valid UUID" not in result

    def test_with_no_workspace_returns_clean_required_message(self):
        agent = _StubAgent(workspace_id=None)
        result = get_organization_operations(agent, organization_id="None")
        assert result == "Organization identifier is required."
        assert "is not a valid UUID" not in result


@pytest.mark.django_db
class TestUpdateOrganizationRegression:
    """The other affected call site — same shape."""

    def test_with_None_string_falls_back_to_agent_workspace(
        self, workspace_factory
    ):
        ws = workspace_factory()
        agent = _StubAgent(workspace_id=str(ws.id))
        result = update_organization(
            agent,
            update_data={
                "organization_id": "None",
                "field": "workspace_name",
                "new_value": "Updated by agent",
            },
        )
        assert "is not a valid UUID" not in result
        # Should have actually updated the workspace.
        ws.refresh_from_db()
        assert ws.workspace_name == "Updated by agent"
