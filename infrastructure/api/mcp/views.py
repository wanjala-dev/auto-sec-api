"""MCP JSON-RPC endpoint backed by the DRF OpenAPI schema.

Security / trust boundary (SEE-204):
- The MCP proxies REST endpoints. When ``MCP_FORWARD_AUTH`` is on it forwards
  ``_get_auto_token()`` — a JWT minted for ``MCP_AUTO_TOKEN_USER_EMAIL`` — so
  calls execute as that *service identity*, not the MCP caller. ``_is_authorized``
  only checks that an Authorization header is present, not that it is valid.
- Therefore money/payment/billing WRITES must never be reachable via the MCP:
  they would bypass the caller's identity and the platform's approval gate
  (SEE-203). ``is_money_write_operation`` excludes them from ``tools/list`` and
  refuses them in ``call_tool``. Reads are unaffected.
- Operator hardening (config, not code): keep ``MCP_AUTO_TOKEN_USER_EMAIL`` a
  least-privilege service account, and gate the MCP endpoint at the network
  layer — the header-presence check is not authentication.
"""
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_NAME = "wanjala-api-mcp"
MCP_SERVER_VERSION = "0.1.0"

DEFAULT_SCHEMA_PATH = "/api/schema/"
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("MCP_API_TIMEOUT_SECONDS", "30"))
SCHEMA_CACHE_TTL_SECONDS = int(os.getenv("MCP_SCHEMA_TTL_SECONDS", "60"))

logger = logging.getLogger("mcp")

_SCHEMA_CACHE: Dict[str, Any] = {
    "data": None,
    "fetched_at": 0.0,
    "etag": None,
    "tools": None,
    "tool_index": None,
    "fetching": False,  # sentinel to prevent thundering herd
}
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = threading.Condition(_SCHEMA_LOCK)

MCP_REQUIRE_AUTH = os.getenv("MCP_REQUIRE_AUTH", "true").lower() in {"1", "true", "yes"}
MCP_AUTO_TOKEN_USER_EMAIL = os.getenv("MCP_AUTO_TOKEN_USER_EMAIL", "")
MCP_ALLOWED_PATH_PREFIXES = [
    p.strip() for p in os.getenv("MCP_ALLOWED_PATH_PREFIXES", "").split(",") if p.strip()
]
MCP_ALLOWED_OPERATION_IDS = {
    p.strip().lower()
    for p in os.getenv("MCP_ALLOWED_OPERATION_IDS", "").split(",")
    if p.strip()
}


def _log_mcp_ready() -> None:
    if os.getenv("MCP_LOG_STARTUP", "true").lower() not in {"1", "true", "yes"}:
        return
    if os.getenv("RUN_MAIN") not in {None, "true"}:
        return
    message = "MCP endpoint ready at /mcp/ (schema: /api/schema/)"
    if logger.hasHandlers():
        logger.info(message)
    else:
        print(message)


_log_mcp_ready()


class ToolError(Exception):
    def __init__(self, code: int, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _requires_auth() -> bool:
    return MCP_REQUIRE_AUTH


def _is_authorized(request) -> bool:
    if not _requires_auth():
        return True
    auth_header = request.headers.get("Authorization")
    return bool(auth_header and auth_header.strip())


def _get_auto_token() -> Optional[str]:
    """Generate a fresh JWT for the configured MCP service user.

    When MCP_AUTO_TOKEN_USER_EMAIL is set, this creates a short-lived access
    token on-the-fly so the MCP proxy never relies on a pre-generated token
    that can expire.
    """
    if not MCP_AUTO_TOKEN_USER_EMAIL:
        return None
    try:
        from django.contrib.auth import get_user_model
        from rest_framework_simplejwt.tokens import AccessToken

        User = get_user_model()
        user = User.objects.filter(email=MCP_AUTO_TOKEN_USER_EMAIL).first()
        if user is None:
            logger.warning("MCP_AUTO_TOKEN_USER_EMAIL=%s not found", MCP_AUTO_TOKEN_USER_EMAIL)
            return None
        token = AccessToken.for_user(user)
        return f"Bearer {str(token)}"
    except Exception as exc:
        logger.warning("MCP auto-token generation failed: %s", exc)
        return None


@method_decorator(csrf_exempt, name="dispatch")
class MCPView(View):
    """Minimal MCP JSON-RPC endpoint backed by the DRF OpenAPI schema."""

    http_method_names = ["get", "post"]

    def post(self, request, *args, **kwargs):
        try:
            request_id = None  # Initialize early for error handling

            if not _is_authorized(request):
                return JsonResponse(
                    _jsonrpc_error(None, -32001, "Unauthorized", {"detail": "Authorization header is required"}),
                    status=401,
                )
            try:
                body_str = request.body.decode("utf-8") or "{}"
                payload = json.loads(body_str)
                # Try to extract id even if JSON is partially valid
                request_id = payload.get("id") if isinstance(payload, dict) else None
            except json.JSONDecodeError as e:
                # For parse errors, try to extract id from raw string as fallback
                # JSON-RPC 2.0 spec allows null id for parse errors, but MCP client is stricter
                # Try to find id in the raw string as a workaround
                try:
                    id_match = re.search(r'"id"\s*:\s*([^,}\]]+)', body_str)
                    if id_match:
                        id_val = id_match.group(1).strip().strip('"\'')
                        if id_val.isdigit():
                            request_id = int(id_val)
                        elif id_val.startswith('"') and id_val.endswith('"'):
                            request_id = id_val[1:-1]
                except:
                    pass
                # Use 0 as fallback id if we can't extract it (MCP client requires non-null)
                if request_id is None:
                    request_id = 0
                return JsonResponse(_jsonrpc_error(request_id, -32700, "Parse error"), status=400)

            method = payload.get("method")
            # request_id already set above, but update if payload has it (but not if it's null)
            if "id" in payload:
                payload_id = payload.get("id")
                # Only update if it's not None (MCP client doesn't accept null ids)
                if payload_id is not None:
                    request_id = payload_id
            params = payload.get("params") or {}

            # Check if this is a notification (id is None/null)
            is_notification = request_id is None
            
            if not method:
                # For notifications, don't send error response
                if is_notification:
                    return HttpResponse(status=204)
                # Use 0 as fallback if request_id is None (shouldn't happen here, but safety)
                error_id = request_id if request_id is not None else 0
                return JsonResponse(_jsonrpc_error(error_id, -32600, "Invalid Request"), status=400)

            if method in {"initialize", "mcp/initialize", "server/initialize"}:
                # Initialize must have an id (it's a request, not a notification)
                if is_notification:
                    return HttpResponse(status=204)
                requested_version = None
                if isinstance(params, dict):
                    requested_version = params.get("protocolVersion")
                return JsonResponse(_jsonrpc_result(request_id, _initialize_result(requested_version)))

            if method in {"initialized", "notifications/initialized"}:
                # Initialized is always a notification (no response expected)
                return HttpResponse(status=204)

            if method == "ping":
                # Ping can be a notification or request
                if is_notification:
                    return HttpResponse(status=204)
                return JsonResponse(_jsonrpc_result(request_id, {}))

            if method == "tools/list":
                # tools/list must be a request, not a notification
                if is_notification:
                    return HttpResponse(status=204)
                try:
                    tools, _ = get_tools(request)
                except ToolError as exc:
                    return JsonResponse(
                        _jsonrpc_error(request_id, exc.code, exc.message, exc.data),
                        status=400,
                    )
                return JsonResponse(_jsonrpc_result(request_id, {"tools": tools}))

            if method == "tools/call":
                # tools/call must be a request, not a notification
                if request_id is None:
                    return HttpResponse(status=204)
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if not name:
                    return JsonResponse(_jsonrpc_error(request_id, -32602, "Missing tool name"), status=400)
                try:
                    result = call_tool(request, name, arguments)
                except ToolError as exc:
                    return JsonResponse(
                        _jsonrpc_error(request_id, exc.code, exc.message, exc.data),
                        status=400,
                    )
                return JsonResponse(_jsonrpc_result(request_id, result))

            if method == "resources/list":
                # resources/list must be a request, not a notification
                if request_id is None:
                    return HttpResponse(status=204)
                return JsonResponse(_jsonrpc_result(request_id, {"resources": get_resources()}))

            if method == "resources/read":
                # resources/read must be a request, not a notification
                if request_id is None:
                    return HttpResponse(status=204)
                uri = params.get("uri")
                if not uri:
                    return JsonResponse(_jsonrpc_error(request_id, -32602, "Missing 'uri'"), status=400)
                try:
                    content = read_resource(request, uri)
                except ToolError as exc:
                    return JsonResponse(
                        _jsonrpc_error(request_id, exc.code, exc.message, exc.data),
                        status=400,
                    )
                return JsonResponse(_jsonrpc_result(request_id, {"contents": [content]}))

            if method == "prompts/list":
                # prompts/list must be a request, not a notification
                if request_id is None:
                    return HttpResponse(status=204)
                return JsonResponse(_jsonrpc_result(request_id, {"prompts": []}))

            if method == "prompts/get":
                # prompts/get must be a request, not a notification
                if request_id is None:
                    return HttpResponse(status=204)
                return JsonResponse(
                    _jsonrpc_error(request_id, -32602, "Prompt not found"),
                    status=400,
                )

            if method.startswith("notifications/"):
                return HttpResponse(status=204)

            if request_id is None:
                return HttpResponse(status=204)
            error_id = request_id if request_id is not None else 0
            return JsonResponse(_jsonrpc_error(error_id, -32601, "Method not found"), status=404)
        except Exception as e:
            # If this was a notification (request_id is None), don't send error response
            if request_id is None:
                return HttpResponse(status=204)
            # Use 0 as fallback id if request_id is None (shouldn't happen here, but safety)
            error_id = request_id if request_id is not None else 0
            return JsonResponse(
                _jsonrpc_error(error_id, -32603, "Internal error", {"detail": str(e), "type": type(e).__name__}),
                status=500
            )

    def get(self, request, *args, **kwargs):
        if not _is_authorized(request):
            return JsonResponse({"detail": "Authorization header is required"}, status=401)
        return JsonResponse(
            {
                "status": "ok",
                "mcp": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "serverInfo": {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
                },
            }
        )


def _initialize_result(requested_version: Optional[str] = None) -> Dict[str, Any]:
    # Always advertise the version *this server* supports, regardless of what
    # the client requested.  Echoing back an unknown version would falsely
    # claim compatibility.
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
        "capabilities": {
            "tools": {
                "listChanged": False  # Indicates tools are supported
            },
            "resources": {
                "subscribe": False,
                "listChanged": False  # Indicates resources are supported
            },
        },
    }


def _jsonrpc_result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure id is never None (use 0 as fallback for MCP client compatibility)
    response_id = request_id if request_id is not None else 0
    return {"jsonrpc": "2.0", "id": response_id, "result": result}


def _jsonrpc_error(
    request_id: Any, code: int, message: str, data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def get_api_base_url(request) -> str:
    override = os.getenv("MCP_API_BASE_URL")
    if override:
        return override.rstrip("/")
    scheme = "https" if request.is_secure() else "http"
    server_name = request.META.get("SERVER_NAME") or ""
    server_port = request.META.get("SERVER_PORT") or ""
    if server_name in {"", "0.0.0.0"}:
        server_name = "127.0.0.1"
    if server_port and server_port not in {"80", "443"}:
        return f"{scheme}://{server_name}:{server_port}"
    return f"{scheme}://{server_name}"


def get_openapi_url(request) -> str:
    override = os.getenv("MCP_OPENAPI_URL")
    if override:
        return override
    return f"{get_api_base_url(request)}{DEFAULT_SCHEMA_PATH}"


def fetch_openapi_schema(request) -> Dict[str, Any]:
    now = time.time()
    with _SCHEMA_READY:
        cached = _SCHEMA_CACHE["data"]
        fetched_at = _SCHEMA_CACHE["fetched_at"]
        etag = _SCHEMA_CACHE.get("etag")
        if cached and now - fetched_at < SCHEMA_CACHE_TTL_SECONDS:
            return cached
        # Another thread is already fetching — wait for it instead of
        # issuing a duplicate HTTP request (thundering herd prevention).
        if _SCHEMA_CACHE["fetching"]:
            _SCHEMA_READY.wait(timeout=DEFAULT_TIMEOUT_SECONDS)
            if _SCHEMA_CACHE["data"]:
                return _SCHEMA_CACHE["data"]
        _SCHEMA_CACHE["fetching"] = True

    headers: Dict[str, str] = {
        "Accept": "application/json",  # Request JSON format instead of YAML
    }
    if etag:
        headers["If-None-Match"] = etag

    if os.getenv("MCP_FORWARD_HOST", "true").lower() in {"1", "true", "yes"}:
        headers.setdefault("Host", request.get_host())

    if os.getenv("MCP_FORWARD_OPENAPI_AUTH", "true").lower() in {"1", "true", "yes"}:
        auto_token = _get_auto_token()
        if auto_token:
            headers["Authorization"] = auto_token
        else:
            auth_header = request.headers.get("Authorization")
            if auth_header:
                headers["Authorization"] = auth_header

    url = get_openapi_url(request)
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = client.get(url, headers=headers)
            # If auth token is expired/invalid, retry without it — the schema
            # endpoint uses IsAuthenticatedOrReadOnly so unauthenticated GETs
            # are allowed, but an *invalid* token triggers a 401.
            if response.status_code == 401 and "Authorization" in headers:
                logger.warning(
                    "Schema fetch returned 401 (auto_token_email=%s) — retrying without auth",
                    MCP_AUTO_TOKEN_USER_EMAIL or "(not set)",
                )
                retry_headers = {k: v for k, v in headers.items() if k != "Authorization"}
                response = client.get(url, headers=retry_headers)
                if response.status_code == 401:
                    raise ToolError(
                        -32000,
                        "OpenAPI schema request failed — both authenticated and "
                        "unauthenticated requests returned 401. Check that "
                        "MCP_AUTO_TOKEN_USER_EMAIL points to a valid user.",
                        {"status": 401, "url": url},
                    )
    except httpx.HTTPError as exc:
        raise ToolError(
            -32000,
            "Failed to fetch OpenAPI schema",
            {"detail": str(exc), "url": url},
        ) from exc

    try:
        with _SCHEMA_READY:
            cached = _SCHEMA_CACHE["data"]
            if response.status_code == 304 and cached:
                _SCHEMA_CACHE["fetched_at"] = now
                _SCHEMA_CACHE["fetching"] = False
                _SCHEMA_READY.notify_all()
                return cached

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ToolError(
                    -32000,
                    "OpenAPI schema request failed",
                    {"status": response.status_code, "body": response.text},
                ) from exc

            try:
                data = response.json()
            except Exception as exc:
                raise ToolError(
                    -32000,
                    "Failed to parse OpenAPI schema JSON",
                    {"detail": str(exc)},
                ) from exc
            _SCHEMA_CACHE["data"] = data
            _SCHEMA_CACHE["fetched_at"] = now
            _SCHEMA_CACHE["etag"] = response.headers.get("ETag")
            _SCHEMA_CACHE["tools"] = None
            _SCHEMA_CACHE["tool_index"] = None
            _SCHEMA_CACHE["fetching"] = False
            _SCHEMA_READY.notify_all()
            return data
    except Exception:
        # Ensure fetching flag is cleared on any failure so other threads
        # don't wait indefinitely.
        with _SCHEMA_READY:
            _SCHEMA_CACHE["fetching"] = False
            _SCHEMA_READY.notify_all()
        raise


def get_tools(request) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    schema = fetch_openapi_schema(request)
    with _SCHEMA_LOCK:
        cached_tools = _SCHEMA_CACHE.get("tools")
        cached_index = _SCHEMA_CACHE.get("tool_index")
        if cached_tools is not None and cached_index is not None:
            return cached_tools, cached_index

        tools, tool_index = build_tools(schema)
        _SCHEMA_CACHE["tools"] = tools
        _SCHEMA_CACHE["tool_index"] = tool_index
        return tools, tool_index


def build_tools(schema: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    tools: List[Dict[str, Any]] = []
    tool_index: Dict[str, Dict[str, Any]] = {}
    used_names: Dict[str, int] = {}

    paths = schema.get("paths", {}) or {}
    for path, path_item in paths.items():
        if path.startswith("/mcp/"):
            continue
        path_parameters = path_item.get("parameters", []) if isinstance(path_item, dict) else []
        for method in ("get", "post", "put", "patch", "delete", "options", "head"):
            operation = path_item.get(method)
            if not operation:
                continue

            parameters = merge_parameters(path_parameters, operation.get("parameters", []))
            operation_id = operation.get("operationId")
            if not is_operation_allowed(path, operation_id):
                continue
            # SEE-204 — never expose money-mutating operations via MCP.
            if is_money_write_operation(method, path):
                continue
            tool_name = build_tool_name(operation_id, method, path, used_names)
            description = (
                operation.get("summary")
                or operation.get("description")
                or f"{method.upper()} {path}"
            )
            input_schema, body_meta = build_input_schema(
                path,
                parameters,
                operation.get("requestBody"),
                schema,
            )

            tools.append(
                {"name": tool_name, "description": description, "inputSchema": input_schema}
            )
            tool_index[tool_name] = {
                "method": method.upper(),
                "path": path,
                "body_required": body_meta["required"],
                "body_content_type": body_meta["content_type"],
                "path_params": body_meta["path_params"],
            }

    return tools, tool_index


def is_operation_allowed(path: str, operation_id: Optional[str]) -> bool:
    if MCP_ALLOWED_PATH_PREFIXES and not any(path.startswith(prefix) for prefix in MCP_ALLOWED_PATH_PREFIXES):
        return False
    if MCP_ALLOWED_OPERATION_IDS:
        if not operation_id:
            return False
        return operation_id.lower() in MCP_ALLOWED_OPERATION_IDS
    return True


_MCP_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Path markers for money / payment / billing surfaces. Matched case-insensitively
# as substrings; gated on a write method so reads (GET) are unaffected.
_MCP_MONEY_MARKERS = (
    "checkout", "refund", "payment", "billing", "donation", "disburs",
    "sponsor_method", "store_connect", "connect_onboard", "braintree",
    "stripe", "setup_intent", "webhook",
)


def is_money_write_operation(method: Optional[str], path: Optional[str]) -> bool:
    """True for a write to a money/payment/billing path (SEE-204).

    The MCP proxies REST endpoints as a service identity (``_get_auto_token``),
    so a money-mutating operation reached through it would bypass the caller's
    identity and the platform's approval gate. Such operations are excluded from
    the tool list and refused at call time — they must go through the
    authenticated, approval-gated product/agent surfaces. Reads are unaffected.
    """
    if (method or "").upper() not in _MCP_WRITE_METHODS:
        return False
    lowered = (path or "").lower()
    return any(marker in lowered for marker in _MCP_MONEY_MARKERS)


def merge_parameters(
    path_parameters: List[Dict[str, Any]], op_parameters: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for param in (path_parameters or []) + (op_parameters or []):
        if not isinstance(param, dict):
            continue
        key = (param.get("name"), param.get("in"))
        merged[key] = param
    return list(merged.values())


def build_tool_name(
    operation_id: Optional[str],
    method: str,
    path: str,
    used_names: Dict[str, int],
) -> str:
    if operation_id:
        base = sanitize_tool_name(operation_id)
    else:
        base = sanitize_tool_name(f"{method}_{path_to_name(path)}")

    count = used_names.get(base, 0)
    used_names[base] = count + 1
    if count:
        return f"{base}_{count + 1}"
    return base


def sanitize_tool_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_")
    return cleaned.lower() or "tool"


def path_to_name(path: str) -> str:
    return path.strip("/").replace("/", "_").replace("{", "by_").replace("}", "")


def build_input_schema(
    path: str,
    parameters: List[Dict[str, Any]],
    request_body: Optional[Dict[str, Any]],
    root_schema: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    path_placeholders = set(re.findall(r"{([^}]+)}", path))
    path_params: Dict[str, Dict[str, Any]] = {}
    query_params: Dict[str, Dict[str, Any]] = {}
    header_params: Dict[str, Dict[str, Any]] = {}
    path_required: List[str] = []
    query_required: List[str] = []
    header_required: List[str] = []

    for param in parameters or []:
        location = param.get("in")
        name = param.get("name")
        if not location or not name:
            continue
        schema = param_schema(param, root_schema)
        if param.get("description") and isinstance(schema, dict):
            schema.setdefault("description", param["description"])
        is_required = bool(param.get("required"))
        if location == "path":
            path_params[name] = schema
            if is_required or name in path_placeholders:
                path_required.append(name)
        elif location == "query":
            query_params[name] = schema
            if is_required:
                query_required.append(name)
        elif location == "header":
            header_params[name] = schema
            if is_required:
                header_required.append(name)

    for placeholder in path_placeholders:
        if placeholder not in path_params:
            path_params[placeholder] = {"type": "string"}
            path_required.append(placeholder)

    input_schema: Dict[str, Any] = {"type": "object", "properties": {}}
    required_groups: List[str] = []

    if path_params:
        input_schema["properties"]["path"] = build_object_schema(path_params, path_required)
        required_groups.append("path")

    if query_params:
        input_schema["properties"]["query"] = build_object_schema(query_params, query_required)
        if query_required:
            required_groups.append("query")

    if header_params:
        input_schema["properties"]["headers"] = build_object_schema(header_params, header_required)
        if header_required:
            required_groups.append("headers")

    body_schema, body_content_type, body_required = extract_request_body_schema(
        request_body, root_schema
    )
    if body_schema is not None:
        input_schema["properties"]["body"] = body_schema
        if body_required:
            required_groups.append("body")

    if required_groups:
        input_schema["required"] = required_groups

    return input_schema, {
        "required": body_required,
        "content_type": body_content_type,
        "path_params": path_placeholders,
    }


def build_object_schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = sorted(set(required))
    return schema


def param_schema(param: Dict[str, Any], root_schema: Dict[str, Any]) -> Dict[str, Any]:
    if "schema" in param:
        return resolve_schema(param["schema"], root_schema)
    content = param.get("content") or {}
    if content:
        for content_type in ("application/json",):
            if content_type in content:
                return resolve_schema(content[content_type].get("schema", {}), root_schema)
        first = next(iter(content.values()))
        return resolve_schema(first.get("schema", {}), root_schema)
    return {"type": "string"}


def extract_request_body_schema(
    request_body: Optional[Dict[str, Any]],
    root_schema: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    if not request_body:
        return None, None, False
    content = request_body.get("content") or {}
    if not content:
        return None, None, bool(request_body.get("required"))

    content_type = None
    schema = None
    if "application/json" in content:
        content_type = "application/json"
        schema = content["application/json"].get("schema")
    else:
        for key in content.keys():
            if "json" in key:
                content_type = key
                schema = content[key].get("schema")
                break
        if content_type is None:
            content_type, info = next(iter(content.items()))
            schema = info.get("schema")

    if schema is None:
        resolved = {"type": "object"}
    else:
        resolved = resolve_schema(schema, root_schema)
    return resolved, content_type, bool(request_body.get("required"))


def resolve_schema(schema: Any, root_schema: Dict[str, Any], seen: Optional[set] = None) -> Any:
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return schema
        if seen is None:
            seen = set()
        if ref in seen:
            return {"type": "object"}
        seen.add(ref)
        target = root_schema
        for part in ref.lstrip("#/").split("/"):
            if not isinstance(target, dict):
                return schema
            target = target.get(part)
            if target is None:
                return schema
        resolved = resolve_schema(target, root_schema, seen)
        extra = {k: v for k, v in schema.items() if k != "$ref"}
        if extra and isinstance(resolved, dict):
            merged = dict(resolved)
            merged.update(extra)
            return merged
        return resolved

    resolved: Dict[str, Any] = {}
    for key, value in schema.items():
        branch_seen = set(seen) if seen else set()
        if isinstance(value, dict):
            resolved[key] = resolve_schema(value, root_schema, branch_seen)
        elif isinstance(value, list):
            resolved[key] = [
                resolve_schema(item, root_schema, set(branch_seen)) for item in value
            ]
        else:
            resolved[key] = value
    return resolved


def get_resources() -> List[Dict[str, Any]]:
    return [
        {
            "uri": "wanjala://overview",
            "name": "Wanjala API overview",
            "description": "High-level product/system summary to orient MCP consumers.",
            "mimeType": "text/markdown",
        },
        {
            "uri": "openapi://schema",
            "name": "OpenAPI schema",
            "description": "DRF OpenAPI schema from /api/schema/",
            "mimeType": "application/json",
        }
    ]


def read_resource(request, uri: str) -> Dict[str, Any]:
    if uri == "wanjala://overview":
        text = (
            "# Wanjala API (Octopai) — High-Level Overview\n\n"
            "Wanjala API is the Django/DRF backend that powers **Octopai** (formerly Octopus), an AI-enabled\n"
            "operating system for organizations and individuals. It provides the core data model, permissions,\n"
            "and API surfaces for budgets/transactions, projects/tasks, teams/memberships, reporting, and\n"
            "AI agent orchestration.\n\n"
            "Key concepts:\n"
            "- **Workspace**: the primary scope for collaboration and finance.\n"
            "- **Sector**: industry/domain context (e.g., nonprofit, education, cybersecurity, personal) used for\n"
            "  onboarding UX and AI routing/entitlements.\n"
            "- **Users + Teams**: membership and access control for shared workspaces.\n"
            "- **Finance**: budgets + transactions are primarily workspace-scoped, optionally linked to recipients.\n"
            "- **Recipients**: canonical target entity for sponsorship/donations.\n\n"
            "Onboarding model (current direction):\n"
            "- Users can enter for **personal use** (recommended backend approach: create a private personal\n"
            "  Workspace with `sector_ids=[\"personal\"]`).\n"
            "- Users can enter via **organization/workspace** flows (join existing or create new), with sector\n"
            "  selection happening early.\n\n"
            "Docs:\n"
            "- `docs/architecture/OCTOPAI_SYSTEM_OVERVIEW.md`\n"
            "- `docs/architecture/SECTORS_ARCHITECTURE.md`\n"
            "- `docs/frontend-handoffs/FRONTEND_ORG_ONBOARDING_HANDOFF.md`\n"
        )
        return {"uri": uri, "mimeType": "text/markdown", "text": text}

    if uri != "openapi://schema":
        raise ToolError(-32602, f"Unknown resource URI: {uri}")
    schema = fetch_openapi_schema(request)
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": json.dumps(schema, ensure_ascii=True),
    }


def call_tool(request, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _, tool_index = get_tools(request)
    if name not in tool_index:
        raise ToolError(-32602, f"Unknown tool: {name}")

    operation = tool_index[name]
    method = operation["method"]
    path_template = operation["path"]
    # SEE-204 — refuse money-writes even if a client supplies the name directly.
    if is_money_write_operation(method, path_template):
        raise ToolError(
            -32601,
            "This operation mutates money or payments and is not available via "
            "MCP. Use the authenticated, approval-gated product surface.",
        )
    path_params = arguments.get("path") or {}
    query_params = arguments.get("query") or {}
    header_params = arguments.get("headers") or {}
    body = arguments.get("body") if "body" in arguments else None

    missing = []
    for param in sorted(operation["path_params"]):
        if param not in path_params:
            missing.append(param)
    if missing:
        raise ToolError(-32602, "Missing path parameters", {"missing": missing})

    if operation["body_required"] and body is None:
        raise ToolError(-32602, "Missing request body")

    path = path_template
    for key, value in (path_params or {}).items():
        path = path.replace(f"{{{key}}}", quote(str(value), safe=""))

    url = f"{get_api_base_url(request)}{path}"

    headers = normalize_headers(header_params)
    if os.getenv("MCP_FORWARD_HOST", "true").lower() in {"1", "true", "yes"}:
        headers.setdefault("Host", request.get_host())
    if os.getenv("MCP_FORWARD_AUTH", "true").lower() in {"1", "true", "yes"}:
        auto_token = _get_auto_token()
        if auto_token:
            headers["Authorization"] = auto_token
        else:
            auth_header = request.headers.get("Authorization")
            if auth_header and "Authorization" not in headers:
                headers["Authorization"] = auth_header

    content_type = operation.get("body_content_type")
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = send_upstream_request(
                client,
                method,
                url,
                query_params,
                headers,
                body,
                content_type,
            )
    except httpx.HTTPError as exc:
        raise ToolError(
            -32000,
            "Upstream API request failed",
            {"detail": str(exc), "url": url},
        ) from exc

    return format_response_result(response)


def normalize_headers(headers: Dict[str, Any]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for key, value in (headers or {}).items():
        if value is None:
            continue
        normalized[str(key)] = str(value)
    return normalized


def send_upstream_request(
    client: httpx.Client,
    method: str,
    url: str,
    query_params: Dict[str, Any],
    headers: Dict[str, str],
    body: Any,
    content_type: Optional[str],
) -> httpx.Response:
    params = query_params or None
    if body is None:
        return client.request(method, url, params=params, headers=headers)

    if content_type:
        headers.setdefault("Content-Type", content_type)
    if content_type and "json" in content_type:
        return client.request(method, url, params=params, headers=headers, json=body)
    return client.request(method, url, params=params, headers=headers, data=body)


def format_response_result(response: httpx.Response) -> Dict[str, Any]:
    content_type = response.headers.get("Content-Type", "")
    payload_text = response.text
    response_json = None

    # Try to parse as JSON regardless of Content-Type — some endpoints
    # return JSON without the header.  One attempt is sufficient.
    try:
        response_json = response.json()
    except (ValueError, json.JSONDecodeError):
        pass

    if response_json is not None:
        payload_text = json.dumps(response_json, ensure_ascii=True)

    result: Dict[str, Any] = {
        "content": [{"type": "text", "text": payload_text}],
        "meta": {
            "status": response.status_code,
            "content_type": content_type,
            "url": str(response.url),
        },
    }
    if response.status_code >= 400:
        result["isError"] = True
    return result
