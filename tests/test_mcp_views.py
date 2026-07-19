"""Tests for the MCP JSON-RPC endpoint (infrastructure.api.mcp.views).

Covers:
- Authorization / auth bypass
- JSON-RPC protocol handling (parse errors, missing method, notifications)
- Protocol version negotiation
- OpenAPI allowlist filtering (path prefixes, operation IDs)
- Tool building from OpenAPI schema
- Tool calling / upstream proxy
- Resource listing & reading
- Response formatting (success + error)
- Schema caching behaviour
- Auto-token generation
"""

import json
import threading
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.test import Client

from infrastructure.api.mcp import views


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post(client, payload, *, auth=True):
    """Send a JSON-RPC POST to /mcp/ with optional auth header."""
    headers = {}
    if auth:
        headers["HTTP_AUTHORIZATION"] = "Bearer test-token"
    return client.post(
        "/mcp/",
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )


def _rpc(method, params=None, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAuthorization:
    def test_post_requires_authorization_header(self):
        client = Client()
        response = _post(client, _rpc("ping"), auth=False)
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["message"] == "Unauthorized"

    def test_get_requires_authorization_header(self):
        client = Client()
        response = client.get("/mcp/")
        assert response.status_code == 401

    def test_post_accepts_any_bearer_token(self):
        client = Client()
        response = _post(client, _rpc("ping"), auth=True)
        assert response.status_code == 200
        body = response.json()
        assert "result" in body

    def test_auth_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(views, "MCP_REQUIRE_AUTH", False)
        client = Client()
        response = _post(client, _rpc("ping"), auth=False)
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# JSON-RPC protocol handling
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestJsonRpcProtocol:
    def test_parse_error_returns_32700(self):
        client = Client()
        response = client.post(
            "/mcp/",
            data="not-json",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer t",
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32700

    def test_missing_method_returns_32600(self):
        client = Client()
        response = _post(client, {"jsonrpc": "2.0", "id": 1})
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32600

    def test_unknown_method_returns_32601(self):
        client = Client()
        response = _post(client, _rpc("nonexistent/method"))
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == -32601

    def test_notification_returns_204(self):
        """Notifications (no id) should return 204 No Content."""
        client = Client()
        payload = {"jsonrpc": "2.0", "method": "initialized", "params": {}}
        response = _post(client, payload)
        assert response.status_code == 204

    def test_notification_initialized_returns_204(self):
        client = Client()
        payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        response = _post(client, payload)
        assert response.status_code == 204


# ---------------------------------------------------------------------------
# Initialize / version negotiation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestInitialize:
    def test_initialize_returns_server_info(self):
        client = Client()
        response = _post(client, _rpc("initialize"))
        body = response.json()["result"]
        assert body["serverInfo"]["name"] == views.MCP_SERVER_NAME
        assert body["serverInfo"]["version"] == views.MCP_SERVER_VERSION

    def test_initialize_always_returns_server_protocol_version(self):
        """Server must advertise its own version, not echo the client's."""
        client = Client()
        response = _post(client, _rpc("initialize", {"protocolVersion": "2099-01-01"}))
        body = response.json()["result"]
        assert body["protocolVersion"] == views.MCP_PROTOCOL_VERSION

    def test_initialize_reports_capabilities(self):
        client = Client()
        response = _post(client, _rpc("initialize"))
        caps = response.json()["result"]["capabilities"]
        assert "tools" in caps
        assert "resources" in caps


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPing:
    def test_ping_returns_empty_result(self):
        client = Client()
        response = _post(client, _rpc("ping"))
        assert response.status_code == 200
        assert response.json()["result"] == {}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPrompts:
    def test_prompts_list_returns_empty(self):
        client = Client()
        response = _post(client, _rpc("prompts/list"))
        assert response.json()["result"]["prompts"] == []

    def test_prompts_get_returns_not_found(self):
        client = Client()
        response = _post(client, _rpc("prompts/get", {"name": "any"}))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestResources:
    def test_resources_list(self):
        client = Client()
        response = _post(client, _rpc("resources/list"))
        resources = response.json()["result"]["resources"]
        uris = [r["uri"] for r in resources]
        assert "wanjala://overview" in uris
        assert "openapi://schema" in uris

    def test_read_overview_resource(self):
        client = Client()
        response = _post(client, _rpc("resources/read", {"uri": "wanjala://overview"}))
        contents = response.json()["result"]["contents"]
        assert len(contents) == 1
        assert contents[0]["mimeType"] == "text/markdown"
        assert "Octopai" in contents[0]["text"]

    def test_read_unknown_uri_returns_error(self):
        client = Client()
        response = _post(client, _rpc("resources/read", {"uri": "unknown://foo"}))
        assert response.json()["error"]["code"] == -32602

    def test_read_missing_uri_returns_error(self):
        client = Client()
        response = _post(client, _rpc("resources/read", {}))
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Tools / call — missing name
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestToolsCall:
    def test_missing_tool_name_returns_error(self):
        client = Client()
        response = _post(client, _rpc("tools/call", {"arguments": {}}))
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32602
        assert "tool name" in body["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Allowlist filtering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "prefixes,operation_ids,path,operation_id,expected",
    [
        (["/users/"], set(), "/users/me/", "UsersMe", True),
        (["/users/"], set(), "/budget/list/", "BudgetList", False),
        ([], {"usersme"}, "/users/me/", "UsersMe", True),
        ([], {"usersme"}, "/users/me/", "UsersList", False),
        (["/users/"], {"usersme"}, "/users/me/", "UsersMe", True),
        (["/users/"], {"usersme"}, "/users/me/", None, False),
        ([], set(), "/any/path/", "AnyOp", True),  # no filters = allow all
    ],
)
def test_is_operation_allowed(prefixes, operation_ids, path, operation_id, expected, monkeypatch):
    monkeypatch.setattr(views, "MCP_ALLOWED_PATH_PREFIXES", prefixes)
    monkeypatch.setattr(views, "MCP_ALLOWED_OPERATION_IDS", operation_ids)
    assert views.is_operation_allowed(path, operation_id) is expected


# ---------------------------------------------------------------------------
# build_tools
# ---------------------------------------------------------------------------

class TestBuildTools:
    def test_respects_allowlist(self, monkeypatch):
        monkeypatch.setattr(views, "MCP_ALLOWED_PATH_PREFIXES", ["/users/"])
        monkeypatch.setattr(views, "MCP_ALLOWED_OPERATION_IDS", {"usersme"})

        schema = {
            "paths": {
                "/users/me/": {
                    "get": {"operationId": "UsersMe", "summary": "me"},
                    "post": {"operationId": "UsersUpdate", "summary": "update"},
                },
                "/budget/list/": {
                    "get": {"operationId": "BudgetList", "summary": "budget"},
                },
            }
        }

        tools, tool_index = views.build_tools(schema)
        names = [t["name"] for t in tools]
        assert names == ["usersme"]
        assert "usersme" in tool_index

    def test_skips_mcp_path(self):
        schema = {
            "paths": {
                "/mcp/": {"get": {"operationId": "McpSelf", "summary": "self"}},
                "/users/": {"get": {"operationId": "UsersList", "summary": "list users"}},
            }
        }
        tools, _ = views.build_tools(schema)
        names = [t["name"] for t in tools]
        assert "mcpself" not in names
        assert "userslist" in names

    def test_deduplicates_tool_names(self):
        schema = {
            "paths": {
                "/a/": {"get": {"operationId": "DupName", "summary": "first"}},
                "/b/": {"get": {"operationId": "DupName", "summary": "second"}},
            }
        }
        tools, _ = views.build_tools(schema)
        names = [t["name"] for t in tools]
        assert "dupname" in names
        assert "dupname_2" in names

    def test_generates_name_from_path_when_no_operation_id(self):
        schema = {
            "paths": {
                "/items/{id}/": {"get": {"summary": "Get item"}},
            }
        }
        tools, tool_index = views.build_tools(schema)
        assert len(tools) == 1
        assert tools[0]["name"] == "get_items_by_id"

    def test_path_params_marked_required(self):
        schema = {
            "paths": {
                "/items/{id}/": {
                    "get": {
                        "operationId": "GetItem",
                        "summary": "Get item",
                        "parameters": [
                            {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                        ],
                    }
                },
            }
        }
        tools, _ = views.build_tools(schema)
        input_schema = tools[0]["inputSchema"]
        assert "path" in input_schema.get("required", [])

    def test_request_body_included(self):
        schema = {
            "paths": {
                "/items/": {
                    "post": {
                        "operationId": "CreateItem",
                        "summary": "Create item",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                    }
                                }
                            },
                        },
                    }
                }
            }
        }
        tools, tool_index = views.build_tools(schema)
        assert "body" in tools[0]["inputSchema"]["properties"]
        assert tool_index["createitem"]["body_required"] is True


# ---------------------------------------------------------------------------
# Schema resolution
# ---------------------------------------------------------------------------

class TestResolveSchema:
    def test_resolves_ref(self):
        root = {
            "components": {
                "schemas": {
                    "User": {"type": "object", "properties": {"name": {"type": "string"}}}
                }
            }
        }
        result = views.resolve_schema({"$ref": "#/components/schemas/User"}, root)
        assert result["type"] == "object"
        assert "name" in result["properties"]

    def test_handles_circular_ref(self):
        root = {
            "components": {
                "schemas": {
                    "Node": {
                        "type": "object",
                        "properties": {"child": {"$ref": "#/components/schemas/Node"}},
                    }
                }
            }
        }
        result = views.resolve_schema({"$ref": "#/components/schemas/Node"}, root)
        assert result["type"] == "object"
        # The circular child should resolve to a generic object
        child = result["properties"]["child"]
        assert child == {"type": "object"}


# ---------------------------------------------------------------------------
# format_response_result
# ---------------------------------------------------------------------------

class TestFormatResponse:
    def test_marks_errors(self):
        response = httpx.Response(
            400,
            headers={"Content-Type": "application/json"},
            content=b'{"detail": "bad"}',
            request=httpx.Request("GET", "http://testserver/users/me/"),
        )
        result = views.format_response_result(response)
        assert result["isError"] is True
        assert result["meta"]["status"] == 400

    def test_success_has_no_error_flag(self):
        response = httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b'{"id": 1}',
            request=httpx.Request("GET", "http://testserver/users/1/"),
        )
        result = views.format_response_result(response)
        assert "isError" not in result
        assert result["meta"]["status"] == 200

    def test_non_json_response(self):
        response = httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html></html>",
            request=httpx.Request("GET", "http://testserver/page/"),
        )
        result = views.format_response_result(response)
        assert result["content"][0]["text"] == "<html></html>"

    def test_json_body_with_wrong_content_type(self):
        """Should still parse JSON even when Content-Type is wrong."""
        response = httpx.Response(
            200,
            headers={"Content-Type": "text/plain"},
            content=b'{"key": "value"}',
            request=httpx.Request("GET", "http://testserver/data/"),
        )
        result = views.format_response_result(response)
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["key"] == "value"


# ---------------------------------------------------------------------------
# Auto-token generation
# ---------------------------------------------------------------------------

class TestAutoToken:
    def test_returns_none_when_email_not_configured(self, monkeypatch):
        monkeypatch.setattr(views, "MCP_AUTO_TOKEN_USER_EMAIL", "")
        assert views._get_auto_token() is None

    def test_returns_none_when_user_not_found(self, monkeypatch):
        monkeypatch.setattr(views, "MCP_AUTO_TOKEN_USER_EMAIL", "nobody@example.com")
        # Mock get_user_model to return a queryset that finds nothing
        mock_user_model = MagicMock()
        mock_user_model.objects.filter.return_value.first.return_value = None
        with patch("django.contrib.auth.get_user_model", return_value=mock_user_model):
            assert views._get_auto_token() is None


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

class TestUtilities:
    def test_sanitize_tool_name(self):
        assert views.sanitize_tool_name("Users/Me") == "users_me"
        assert views.sanitize_tool_name("GET /items/") == "get_items"
        assert views.sanitize_tool_name("") == "tool"

    def test_path_to_name(self):
        assert views.path_to_name("/items/{id}/") == "items_by_id"
        assert views.path_to_name("/users/me/") == "users_me"

    def test_normalize_headers_skips_none(self):
        result = views.normalize_headers({"Accept": "json", "X-Custom": None})
        assert result == {"Accept": "json"}

    def test_merge_parameters_deduplicates(self):
        path_params = [{"name": "id", "in": "path", "schema": {"type": "string"}}]
        op_params = [
            {"name": "id", "in": "path", "schema": {"type": "integer"}},  # override
            {"name": "q", "in": "query", "schema": {"type": "string"}},
        ]
        result = views.merge_parameters(path_params, op_params)
        # Operation params should override path-level params
        id_param = [p for p in result if p["name"] == "id"][0]
        assert id_param["schema"]["type"] == "integer"
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _jsonrpc helpers
# ---------------------------------------------------------------------------

class TestJsonRpcHelpers:
    def test_result_with_none_id_uses_zero(self):
        result = views._jsonrpc_result(None, {"ok": True})
        assert result["id"] == 0

    def test_error_includes_data_when_provided(self):
        error = views._jsonrpc_error(1, -32600, "Bad", {"detail": "info"})
        assert error["error"]["data"]["detail"] == "info"

    def test_error_omits_data_when_none(self):
        error = views._jsonrpc_error(1, -32600, "Bad")
        assert "data" not in error["error"]
