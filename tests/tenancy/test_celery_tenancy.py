"""Tenancy across the queue — the boundary a task has no request to bind from.

The test that matters here is the inheritance one. A prefork child runs up to
``worker_max_tasks_per_child`` tasks in the same process, so "only bind when a
header is present" silently means "inherit the previous task's customer".
"""

from __future__ import annotations

import pytest

from components.shared_platform.infrastructure.tenancy.context import (
    KIND_DEDICATED,
    KIND_POOLED,
    TenantContext,
    get_current_tenant,
    tenant_context,
)
from components.shared_platform.infrastructure.tenancy.workspace_context import (
    get_current_workspace,
    workspace_context,
)
from infrastructure.celery.tenancy_signals import (
    _TENANT_HEADER,
    _WORKSPACE_HEADER,
    _bind_tenancy,
    _stamp_tenancy,
    _unbind_tenancy,
)

pytestmark = [pytest.mark.unit, pytest.mark.unbound_tenancy]

WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"
SENSO = TenantContext(kind=KIND_DEDICATED, tenant_id="t-1", subdomain="senso", db_alias="tenant_senso")


class _FakeTask:
    """Stands in for a Celery task with its request headers attached."""

    def __init__(self, **headers):
        self.request = type("_Req", (), headers)()


def _run_task(task_id: str, task: _FakeTask):
    """prerun → observe → postrun, the way a worker would."""
    _bind_tenancy(task_id=task_id, task=task)
    observed = (get_current_tenant(), get_current_workspace())
    _unbind_tenancy(task_id=task_id)
    return observed


class TestDispatchStampsTheOutgoingMessage:
    def test_tenant_and_workspace_are_recorded(self):
        headers: dict = {}
        with tenant_context(SENSO), workspace_context(WS_A):
            _stamp_tenancy(headers=headers)

        assert headers[_TENANT_HEADER]["db_alias"] == "tenant_senso"
        assert headers[_WORKSPACE_HEADER] == WS_A

    def test_nothing_bound_stamps_nothing(self):
        headers: dict = {}
        _stamp_tenancy(headers=headers)
        assert headers == {}


class TestTheWorkerBindsWhatWasStamped:
    def test_a_stamped_task_runs_under_that_tenant(self):
        task = _FakeTask(
            **{
                _TENANT_HEADER: {
                    "kind": KIND_DEDICATED,
                    "tenant_id": "t-1",
                    "subdomain": "senso",
                    "db_alias": "tenant_senso",
                    "workspace_id": None,
                },
                _WORKSPACE_HEADER: WS_A,
            }
        )
        tenant, workspace = _run_task("task-1", task)
        assert tenant.db_alias == "tenant_senso"
        assert workspace == WS_A

    def test_bindings_are_released_after_the_task(self):
        task = _FakeTask(**{_WORKSPACE_HEADER: WS_A})
        _run_task("task-1", task)
        assert get_current_tenant() is None
        assert get_current_workspace() is None

    def test_a_malformed_header_binds_nothing_rather_than_something_wrong(self):
        task = _FakeTask(**{_TENANT_HEADER: {"kind": "silo", "db_alias": "x"}})
        tenant, _ = _run_task("task-1", task)
        assert tenant is None


class TestATaskNeverInheritsThePreviousTasksTenant:
    """The bug the celery skill surfaced.

    A prefork child runs up to ``worker_max_tasks_per_child`` (50) tasks in one
    process. If prerun only binds when a header is present, an unstamped task
    runs under whatever the previous task left bound — a cross-tenant read that
    no call site looks wrong at.
    """

    def test_an_unstamped_task_is_unbound_even_if_the_previous_postrun_was_MISSED(self):
        """The hazard is an unpaired signal, not the happy path.

        With prerun and postrun both firing, a conditional bind looks fine —
        the reset cleans up regardless. The bug only shows when postrun is
        missed: a handler that raised, a signal that did not fire, a task killed
        between the two. Then the next task on that process inherits.

        Binding unconditionally in prerun is what makes that survivable, so this
        test deliberately does NOT call postrun for the first task.
        """
        stamped = _FakeTask(
            **{
                _TENANT_HEADER: {
                    "kind": KIND_DEDICATED,
                    "tenant_id": "t-1",
                    "subdomain": "senso",
                    "db_alias": "tenant_senso",
                    "workspace_id": None,
                },
                _WORKSPACE_HEADER: WS_A,
            }
        )
        _bind_tenancy(task_id="task-1", task=stamped)  # …and postrun never runs
        assert get_current_tenant().db_alias == "tenant_senso"

        # Same process, next task, no headers at all.
        _bind_tenancy(task_id="task-2", task=_FakeTask())
        try:
            assert get_current_tenant() is None, "unstamped task inherited the previous tenant"
            assert get_current_workspace() is None, "unstamped task inherited the previous workspace"
        finally:
            _unbind_tenancy(task_id="task-2")
            _unbind_tenancy(task_id="task-1")

    def test_a_differently_stamped_task_does_not_bleed(self):
        a = _FakeTask(**{_WORKSPACE_HEADER: WS_A})
        b = _FakeTask(**{_WORKSPACE_HEADER: WS_B})
        assert _run_task("task-1", a)[1] == WS_A
        assert _run_task("task-2", b)[1] == WS_B

    def test_postrun_without_a_matching_prerun_is_harmless(self):
        """Signals can fire unpaired; unbinding must not explode."""
        _unbind_tenancy(task_id="never-seen")


class TestPooledDispatchRoundTrips:
    def test_the_shared_console_survives_the_queue(self):
        headers: dict = {}
        with tenant_context(TenantContext(kind=KIND_POOLED)), workspace_context(WS_B):
            _stamp_tenancy(headers=headers)

        task = _FakeTask(**{k: v for k, v in headers.items()})
        tenant, workspace = _run_task("task-1", task)
        assert tenant.kind == KIND_POOLED
        assert workspace == WS_B
