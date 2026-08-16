"""The WebSocket stack binds the tenant — channels bypasses HTTP middleware.

Found live on 2026-08-16: `infrastructure/realtime/` ran ORM queries (the JWT
user lookup, the membership checks) with nothing bound, so the fail-closed
router killed every connection with ``UnboundTenantError``. These tests pin
the WS twin of the HTTP contract: bind from the Host header, fail closed on
unknown subdomains (close 4404), enforce host↔workspace agreement (4403),
clear on the way out.

The middleware is driven with hand-rolled ASGI plumbing rather than
``WebsocketCommunicator`` — its contract is pure ASGI (scope/receive/send),
and hand-rolling keeps the tests free of channel-layer and DB-in-thread
fixtures. Registry resolution itself is covered by the HTTP-side tests; both
transports share ``resolve_tenant_context``.
"""

from __future__ import annotations

import asyncio

import pytest
from asgiref.sync import sync_to_async

from components.shared_platform.infrastructure.tenancy import websocket as ws_tenancy
from components.shared_platform.infrastructure.tenancy.context import (
    KIND_POOLED,
    POOLED_CONTEXT,
    TenantContext,
    get_current_tenant,
)
from components.shared_platform.infrastructure.tenancy.websocket import (
    CLOSE_UNKNOWN_TENANT,
    CLOSE_WORKSPACE_MISMATCH,
    TenantBindWebsocketMiddleware,
    tenant_allows_workspace,
)
from components.shared_platform.infrastructure.tenancy.workspace_context import (
    get_current_workspace,
)

# These tests assert against the genuinely unbound state the middleware
# starts from in production; the autouse pooled-binding fixture must not run.
pytestmark = pytest.mark.unbound_tenancy

WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"


def _scope(host: bytes) -> dict:
    return {"type": "websocket", "headers": [(b"host", host)]}


class _Probe:
    """Inner app that records what the consumer's world looks like."""

    def __init__(self):
        self.called = False
        self.tenant_in_task = None
        self.tenant_in_sync_hop = None

    async def __call__(self, scope, receive, send):
        self.called = True
        self.tenant_in_task = get_current_tenant()
        # The live bug's shape: consumers reach the ORM through
        # database_sync_to_async worker threads. asgiref copies the current
        # context into the thread — assert the binding survives the hop.
        self.tenant_in_sync_hop = await sync_to_async(get_current_tenant)()


async def _connect_once():
    return {"type": "websocket.connect"}


def _drive(app, scope):
    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, _receive_connect(), send))
    return sent


def _receive_connect():
    async def receive():
        return {"type": "websocket.connect"}

    return receive


class TestTenantBindWebsocketMiddleware:
    def test_bare_host_binds_pooled_for_the_connection(self):
        probe = _Probe()
        _drive(TenantBindWebsocketMiddleware(probe), _scope(b"testserver"))
        assert probe.tenant_in_task == POOLED_CONTEXT

    def test_the_binding_reaches_database_sync_to_async_hops(self):
        probe = _Probe()
        _drive(TenantBindWebsocketMiddleware(probe), _scope(b"testserver"))
        assert probe.tenant_in_sync_hop == POOLED_CONTEXT

    def test_ip_literal_host_binds_pooled(self):
        """Skill trap 3g applies to WS too — a pod-IP host is not a tenant."""
        probe = _Probe()
        _drive(TenantBindWebsocketMiddleware(probe), _scope(b"10.1.2.128:8000"))
        assert probe.tenant_in_task == POOLED_CONTEXT

    def test_unknown_subdomain_closes_4404_without_reaching_the_stack(self, monkeypatch):
        monkeypatch.setattr(ws_tenancy, "resolve_tenant_context", lambda host: None)
        probe = _Probe()
        sent = _drive(TenantBindWebsocketMiddleware(probe), _scope(b"nope.auto-sec.ai"))
        assert sent == [{"type": "websocket.close", "code": CLOSE_UNKNOWN_TENANT}]
        assert probe.called is False
        # Auth never ran, nothing was bound: the deny must not confirm the
        # subdomain's absence by behaving differently deeper in the stack.

    def test_the_binding_is_cleared_when_the_connection_ends(self):
        """Asserted INSIDE the same async context — after asyncio.run() the
        caller is back in its own context and would see None even if the
        finally were deleted, which is exactly the vacuous pass to avoid."""

        async def main():
            await TenantBindWebsocketMiddleware(_Probe())(_scope(b"testserver"), _receive_connect(), _noop_send)
            return get_current_tenant(), get_current_workspace()

        assert asyncio.run(main()) == (None, None)

    def test_cleared_even_when_the_consumer_raises(self):
        class _Boom:
            async def __call__(self, scope, receive, send):
                raise RuntimeError("consumer crashed")

        async def main():
            with pytest.raises(RuntimeError):
                await TenantBindWebsocketMiddleware(_Boom())(_scope(b"testserver"), _receive_connect(), _noop_send)
            return get_current_tenant()

        assert asyncio.run(main()) is None

    def test_non_websocket_scopes_pass_through_unbound(self):
        probe = _Probe()
        _drive(TenantBindWebsocketMiddleware(probe), {"type": "http", "headers": []})
        assert probe.called is True
        assert probe.tenant_in_task is None


async def _noop_send(message):
    return None


class TestTenantAllowsWorkspace:
    def test_an_unpinned_host_allows_any_workspace(self):
        assert tenant_allows_workspace({"tenant": POOLED_CONTEXT}, WS_A)

    def test_a_pinned_host_allows_its_own_workspace(self):
        pinned = TenantContext(kind=KIND_POOLED, tenant_id="t", subdomain="senso", workspace_id=WS_A)
        assert tenant_allows_workspace({"tenant": pinned}, WS_A)

    def test_a_pinned_host_refuses_another_workspace(self):
        pinned = TenantContext(kind=KIND_POOLED, tenant_id="t", subdomain="senso", workspace_id=WS_A)
        assert not tenant_allows_workspace({"tenant": pinned}, WS_B)

    def test_a_scope_without_a_tenant_is_not_the_enforcement_point(self):
        """No tenant on the scope means the middleware isn't wired; allowing
        here is safe because the router's fail-closed raise is the backstop
        the very first query hits."""
        assert tenant_allows_workspace({}, WS_A)


class TestWorkspaceConsumersEnforceTheHostPin:
    def _drive_consumer(self, consumer_app, workspace_in_url):
        class _User:
            is_authenticated = True
            id = "0f0e0d0c-0b0a-0908-0706-050403020100"

        pinned = TenantContext(kind=KIND_POOLED, tenant_id="t", subdomain="senso", workspace_id=WS_A)
        scope = {
            "type": "websocket",
            "headers": [],
            "user": _User(),
            "tenant": pinned,
            "url_route": {
                "kwargs": {"workspace_id": workspace_in_url, "resource_type": "agent_run", "resource_id": "r1"}
            },
        }
        messages = [
            {"type": "websocket.connect"},
            {"type": "websocket.disconnect", "code": 1000},
        ]
        sent = []

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        asyncio.run(consumer_app(scope, receive, send))
        return sent

    def test_activity_consumer_refuses_a_workspace_the_host_does_not_pin(self):
        from infrastructure.realtime.consumers import WorkspaceActivityConsumer

        sent = self._drive_consumer(WorkspaceActivityConsumer.as_asgi(), WS_B)
        assert {"type": "websocket.close", "code": CLOSE_WORKSPACE_MISMATCH} in sent

    def test_resource_consumer_refuses_a_workspace_the_host_does_not_pin(self):
        from infrastructure.realtime.consumers import ResourceStreamConsumer

        sent = self._drive_consumer(ResourceStreamConsumer.as_asgi(), WS_B)
        assert {"type": "websocket.close", "code": CLOSE_WORKSPACE_MISMATCH} in sent


class TestTheAsgiStackIsWired:
    def test_the_websocket_stack_is_wrapped_in_the_tenant_bind_middleware(self):
        """Structural, not source-grep: the outermost websocket app must BE
        the tenant bind — auth inside it already needs the database."""
        import api.asgi

        assert isinstance(
            api.asgi.application.application_mapping["websocket"],
            TenantBindWebsocketMiddleware,
        )
