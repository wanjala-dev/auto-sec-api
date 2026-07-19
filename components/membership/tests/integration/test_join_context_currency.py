"""The public join-context endpoint must surface the workspace's operating
currency so the donate hero renders the right symbol (e.g. CA$), not a
hardcoded USD "$" fallback.

Regression: a CAD workspace's recipient rendered "$" because the
``RecipientFinancialAggregate.currency`` defaults to "USD" before any
donation reconciles and was preferred over the workspace's CAD default.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _join_context_url(workspace_id, context, target_id):
    return f"/api/v1/membership/join/context/{workspace_id}/{context}/{target_id}/"


class TestJoinContextCurrency:
    def test_recipient_uses_workspace_currency_not_aggregate_default(
        self, api_client, recipient_factory, workspace_factory
    ):
        """A CAD workspace's recipient must report CAD even when the
        financial aggregate still carries its USD default (0 raised)."""
        workspace = workspace_factory(default_currency="CAD")
        recipient = recipient_factory(workspace=workspace)

        res = api_client.get(
            _join_context_url(workspace.id, "recipient", recipient.id)
        )

        assert res.status_code == 200
        assert res.data["currency"] == "CAD"

    def test_recipient_falls_back_to_usd_when_workspace_currency_missing(
        self, api_client, recipient_factory, workspace_factory
    ):
        workspace = workspace_factory(default_currency="")
        recipient = recipient_factory(workspace=workspace)

        res = api_client.get(
            _join_context_url(workspace.id, "recipient", recipient.id)
        )

        assert res.status_code == 200
        assert res.data["currency"] == "USD"
