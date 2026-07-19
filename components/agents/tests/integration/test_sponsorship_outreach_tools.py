"""DB-backed integration tests for the sponsorship outreach tools.

Exercises the agent-tool path end-to-end: tool function → use case →
ORM repository → DB row → list tool → formatted output. Both tools
share the same provider, so testing them together covers the realistic
"log then list" workflow the chat path goes through.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    sponsorship_agent as sponsorship_tools,
)


pytestmark = pytest.mark.django_db


def _agent(workspace, user):
    return SimpleNamespace(
        workspace_id=str(workspace.id),
        user_id=str(user.id),
    )


class TestLogOutreachTool:
    def test_logs_a_call_against_donor_name(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.log_outreach(
            agent,
            '{"kind": "call", "donor_name": "Jane Doe", '
            '"outcome": "contacted", "notes": "Asked about year-end gift."}',
        )

        assert "Logged outreach" in result
        assert "call" in result
        assert "Jane Doe" in result
        assert "contacted" in result

    def test_rejects_missing_kind(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.log_outreach(
            agent, '{"donor_name": "Jane"}'
        )

        assert "kind is required" in result

    def test_rejects_missing_donor_identifier(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.log_outreach(
            agent, '{"kind": "call"}'
        )

        assert "Donor identification is required" in result

    def test_missing_workspace_refused(self, user_factory):
        agent = SimpleNamespace(
            workspace_id=None, user_id=str(user_factory().id)
        )

        result = sponsorship_tools.log_outreach(
            agent, '{"kind": "call", "donor_name": "Jane"}'
        )

        assert "No workspace context" in result

    def test_alias_kind_phone_maps_to_call(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.log_outreach(
            agent, '{"kind": "phone", "donor_name": "Jane"}'
        )

        assert "call" in result.lower()


class TestListOutreachTool:
    def test_empty_workspace_returns_explanatory_message(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.list_outreach(agent, "{}")

        assert "No outreach logged" in result

    def test_lists_previously_logged_outreach(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        sponsorship_tools.log_outreach(
            agent,
            '{"kind": "email", "donor_name": "Alice", '
            '"outcome": "committed"}',
        )
        sponsorship_tools.log_outreach(
            agent,
            '{"kind": "meeting", "donor_email": "bob@example.test"}',
        )

        result = sponsorship_tools.list_outreach(agent, "{}")

        assert "Outreach (2)" in result
        assert "Alice" in result
        assert "bob@example.test" in result

    def test_workspace_isolation_in_list(
        self, user_factory, workspace_factory
    ):
        owner_a = user_factory()
        owner_b = user_factory()
        ws_a = workspace_factory(owner=owner_a)
        ws_b = workspace_factory(owner=owner_b)

        sponsorship_tools.log_outreach(
            _agent(ws_a, owner_a),
            '{"kind": "call", "donor_name": "Workspace A donor"}',
        )
        sponsorship_tools.log_outreach(
            _agent(ws_b, owner_b),
            '{"kind": "call", "donor_name": "Workspace B donor"}',
        )

        # Workspace A view excludes workspace B's logs.
        a_result = sponsorship_tools.list_outreach(
            _agent(ws_a, owner_a), "{}"
        )
        assert "Workspace A donor" in a_result
        assert "Workspace B donor" not in a_result
