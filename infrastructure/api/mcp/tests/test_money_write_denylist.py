"""SEE-204 — the MCP must not expose or proxy money-mutating operations.

The MCP proxies REST endpoints as a service identity, so money-writes reached
through it would bypass the caller's identity and the approval gate. They are
excluded from the tool list and refused at call time; reads are unaffected.
"""

from __future__ import annotations

import pytest

from infrastructure.api.mcp.views import build_tools, is_money_write_operation


class TestIsMoneyWriteOperation:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("POST", "/payment/checkout/"),
            ("POST", "/sponsorship/donations/donate/"),
            ("POST", "/store/{id}/refund/"),
            ("post", "/workspaces/billing/plan/change/"),
            ("DELETE", "/grants/disbursements/{id}/"),
            ("POST", "/workspaces/payments/sponsor_methods/"),
        ],
    )
    def test_flags_money_writes(self, method, path):
        assert is_money_write_operation(method, path) is True

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/payment/checkout/"),  # read of a money path is fine
            ("GET", "/workspaces/billing/overview/"),
            ("POST", "/project/create/"),  # write, but not money
            ("PATCH", "/budget/transaction/{id}/"),  # budget edit, not a payment
            ("POST", "/content/drafts/"),
        ],
    )
    def test_does_not_flag_reads_or_non_money_writes(self, method, path):
        assert is_money_write_operation(method, path) is False


class TestBuildToolsExclusion:
    def _schema(self):
        body = {"content": {"application/json": {"schema": {"type": "object"}}}}
        return {
            "paths": {
                "/budget/summary/": {"get": {"operationId": "budget_summary", "summary": "Budget"}},
                "/payment/checkout/": {
                    "post": {
                        "operationId": "payment_checkout",
                        "summary": "Checkout",
                        "requestBody": body,
                    }
                },
                "/project/create/": {
                    "post": {
                        "operationId": "project_create",
                        "summary": "Create project",
                        "requestBody": body,
                    }
                },
            }
        }

    def test_money_write_is_not_advertised(self):
        _tools, tool_index = build_tools(self._schema())

        paths = {op["path"] for op in tool_index.values()}
        assert "/payment/checkout/" not in paths

    def test_reads_and_non_money_writes_are_advertised(self):
        _tools, tool_index = build_tools(self._schema())

        paths = {op["path"] for op in tool_index.values()}
        assert "/budget/summary/" in paths
        assert "/project/create/" in paths
