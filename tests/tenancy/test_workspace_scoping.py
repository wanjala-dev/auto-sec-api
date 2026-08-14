"""Phase 1 proofs: workspace binding, the scoped manager, host↔workspace agreement.

Same discipline as Phase 0 — the tests that matter are the ones that watch
something be REFUSED.
"""

from __future__ import annotations

import asyncio

import pytest
from django.db import models

from components.shared_platform.infrastructure.tenancy.context import (
    KIND_DEDICATED,
    KIND_POOLED,
    TenantContext,
)
from components.shared_platform.infrastructure.tenancy.managers import (
    WorkspaceScopedManager,
    WorkspaceScopedModel,
)
from components.shared_platform.infrastructure.tenancy.middleware import TenantHostMiddleware
from infrastructure.persistence.tenancy.models import Tenant
from components.shared_platform.infrastructure.tenancy.workspace_context import (
    UnboundWorkspaceError,
    get_current_workspace,
    without_workspace_scope,
    workspace_context,
)

pytestmark = pytest.mark.unit

WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"


def _manager_on(model):
    """A scoped manager bound to a real model, the way Django binds one."""
    manager = WorkspaceScopedManager()
    manager.model = model
    return manager


class TestTheManagerFailsClosed:
    """The manager must never treat "unbound" as "all workspaces"."""

    def test_querying_with_no_workspace_bound_RAISES(self):
        """The fail-open shape returns every customer's rows from a call site
        that reads as scoped. This is the test that stops it coming back.

        Note it raises BEFORE touching the database — no query is built, so a
        missing binding cannot leak rows even momentarily.
        """
        assert get_current_workspace() is None
        with pytest.raises(UnboundWorkspaceError) as err:
            _manager_on(Tenant).get_queryset()
        assert "tenancy.Tenant" in str(err.value)

    def test_the_error_names_the_escape_hatch(self):
        """A guard nobody can get past gets deleted. The message has to say how
        to cross the boundary deliberately."""
        with pytest.raises(UnboundWorkspaceError) as err:
            _manager_on(Tenant).get_queryset()
        message = str(err.value)
        assert "unscoped" in message and "without_workspace_scope" in message

    @pytest.mark.django_db
    def test_a_bound_workspace_filters_rather_than_raising(self):
        with workspace_context(WS_A):
            sql = str(_manager_on(Tenant).get_queryset().query)
        assert "workspace_id" in sql


class TestWorkspaceBinding:
    def test_bind_and_read(self):
        with workspace_context(WS_A):
            assert get_current_workspace() == WS_A
        assert get_current_workspace() is None

    def test_binding_is_released_when_the_body_raises(self):
        with pytest.raises(RuntimeError), workspace_context(WS_A):
            raise RuntimeError("boom")
        assert get_current_workspace() is None

    def test_uuid_is_normalised_to_string(self):
        import uuid

        u = uuid.UUID(WS_A)
        with workspace_context(u):
            assert get_current_workspace() == WS_A

    def test_without_workspace_scope_is_explicit_and_restores(self):
        with workspace_context(WS_A):
            with without_workspace_scope():
                assert get_current_workspace() is None
            assert get_current_workspace() == WS_A

    def test_concurrent_tasks_keep_separate_workspaces(self):
        """Same ASGI hazard as the tenant binding — proven, not assumed."""
        seen: dict[str, str | None] = {}

        async def run_as(name: str, ws: str, pause: float):
            with workspace_context(ws):
                await asyncio.sleep(pause)
                seen[name] = get_current_workspace()

        async def main():
            await asyncio.gather(run_as("a", WS_A, 0.02), run_as("b", WS_B, 0.01))

        asyncio.run(main())
        assert seen == {"a": WS_A, "b": WS_B}


class TestTheAbstractBaseWiresBothManagers:
    """Django refuses ``.objects`` on an abstract model, so inspect what a
    concrete subclass would inherit — the declared managers themselves."""

    def test_objects_is_scoped_and_unscoped_is_plain(self):
        declared = {m.name: m for m in WorkspaceScopedModel._meta.local_managers}
        assert isinstance(declared["objects"], WorkspaceScopedManager)
        assert type(declared["unscoped"]) is models.Manager

    def test_the_safe_manager_is_the_default_one(self):
        """`objects` is what gets typed without thinking; it must be the scoped
        one, with the crossing spelled out as `unscoped`."""
        assert WorkspaceScopedModel._meta.local_managers[0].name == "objects"

    def test_it_is_abstract(self):
        assert WorkspaceScopedModel._meta.abstract


class TestHostWorkspaceAgreement:
    """The enforcement that makes a subdomain more than decoration.

    Without it, a token for workspace A used against senso.auto-sec.ai is served
    happily and the host means nothing.
    """

    @staticmethod
    def _run(tenant: TenantContext | None, url_workspace: str | None):
        mw = TenantHostMiddleware(lambda r: "OK")

        class _Req:
            pass

        request = _Req()
        if tenant is not None:
            request.tenant = tenant
        kwargs = {} if url_workspace is None else {"workspace_id": url_workspace}
        return mw.process_view(request, None, (), kwargs), request

    def test_a_host_pinned_to_one_workspace_refuses_another(self):
        pinned = TenantContext(kind=KIND_POOLED, tenant_id="t", subdomain="senso", workspace_id=WS_A)
        response, _ = self._run(pinned, WS_B)
        assert response is not None and response.status_code == 403

    def test_the_matching_workspace_is_allowed_and_bound(self):
        pinned = TenantContext(kind=KIND_POOLED, tenant_id="t", subdomain="senso", workspace_id=WS_A)
        response, request = self._run(pinned, WS_A)
        assert response is None
        assert request._workspace_token is not None

    def test_an_unpinned_host_allows_any_workspace(self):
        """The shared console serves many customers; the workspace decides."""
        unpinned = TenantContext(kind=KIND_POOLED)
        response, _ = self._run(unpinned, WS_B)
        assert response is None

    def test_a_url_without_a_workspace_binds_nothing(self):
        response, request = self._run(TenantContext(kind=KIND_POOLED), None)
        assert response is None
        assert not hasattr(request, "_workspace_token")

    def test_dedicated_host_also_enforces_when_pinned(self):
        pinned = TenantContext(
            kind=KIND_DEDICATED,
            tenant_id="t",
            subdomain="senso",
            db_alias="tenant_senso",
            workspace_id=WS_A,
        )
        response, _ = self._run(pinned, WS_B)
        assert response is not None and response.status_code == 403


class TestTheTokenIsNotStoredOnTheMiddleware:
    """A middleware instance is shared by every request in the process.

    Per-request state on `self` leaks between concurrent requests — the exact
    class of bug this subsystem exists to prevent, and one it would be
    embarrassing to introduce while preventing it.
    """

    def test_two_requests_through_one_instance_do_not_share_a_token(self):
        mw = TenantHostMiddleware(lambda r: "OK")

        class _Req:
            pass

        a, b = _Req(), _Req()
        a.tenant = b.tenant = TenantContext(kind=KIND_POOLED)
        mw.process_view(a, None, (), {"workspace_id": WS_A})
        mw.process_view(b, None, (), {"workspace_id": WS_B})

        assert a._workspace_token is not b._workspace_token
        assert not hasattr(mw, "_workspace_token") or mw.__dict__.get("_workspace_token") is None
