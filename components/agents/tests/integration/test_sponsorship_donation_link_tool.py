"""DB-backed integration tests for the ``create_donation_link`` agent tool."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    sponsorship_agent as sponsorship_tools,
)


pytestmark = pytest.mark.django_db


def _agent(workspace, user):
    return SimpleNamespace(
        workspace_id=str(workspace.id), user_id=str(user.id)
    )


class TestCreateDonationLinkTool:
    def test_creates_link_for_donor_name(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.create_donation_link(
            agent,
            '{"donor_name": "Jane Doe", "amount": "50"}',
        )

        assert "Donation link created" in result
        assert "Jane Doe" in result
        assert "/donate/" in result
        assert "$50" in result

    def test_default_currency_is_usd(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.create_donation_link(
            agent, '{"donor_name": "Jane"}'
        )

        assert "USD" in result

    def test_custom_currency_uppercased(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.create_donation_link(
            agent, '{"donor_name": "Jane", "currency": "kes"}'
        )

        assert "KES" in result

    def test_rejects_missing_donor_identifier(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.create_donation_link(agent, "{}")

        assert "Donor identification is required" in result

    def test_rejects_invalid_currency(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.create_donation_link(
            agent, '{"donor_name": "Jane", "currency": "DOLLAR"}'
        )

        assert "3-character ISO code" in result

    def test_rejects_non_numeric_amount(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.create_donation_link(
            agent, '{"donor_name": "Jane", "amount": "fifty bucks"}'
        )

        assert "amount must be a positive decimal" in result

    def test_missing_workspace_refused(self, user_factory):
        agent = SimpleNamespace(
            workspace_id=None, user_id=str(user_factory().id)
        )

        result = sponsorship_tools.create_donation_link(
            agent, '{"donor_name": "Jane"}'
        )

        assert "No workspace context" in result

    def test_amount_without_sign_passes(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = sponsorship_tools.create_donation_link(
            agent, '{"donor_name": "Jane", "amount": "200.50"}'
        )

        assert "$200.50" in result
