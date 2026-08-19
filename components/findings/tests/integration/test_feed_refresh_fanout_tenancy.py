"""A feed refresh rescores EVERY tenant's findings, not just the pool's.

THE FAILURE STORY this pins. EPSS and the CISA KEV catalog are global reference
data — identical for every customer, ~280k rows — so ``vuln_intel.refresh_feeds``
runs ONCE, bound to the pooled console (``mode="shared"`` on its beat entry). The
``VulnIntelRefreshed`` event it publishes therefore arrives at this handler
stamped POOLED.

The handler's contract is "rescore every workspace with findings". Under the
inherited binding it listed only the pooled console's workspaces, so a
dedicated-tier tenant's findings would sit frozen against a snapshot that had
moved — a CVE newly entering KEV, or an EPSS score jumping, would never reach
them — while the log line still read ``fanout workspaces=N``. Silent, permanent
staleness for exactly the customers paying for isolation.

The partition is real: on the live cluster (2026-08-19) the pool held 10,261
findings across 6 workspaces and each dedicated database answered separately.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone

from components.findings.application.handlers.finding_risk_recompute_handler import (
    rescore_all_workspaces_on_feed_refresh,
)
from components.shared_kernel.domain.events import VulnIntelRefreshed
from components.shared_platform.infrastructure.tenancy.sweep import POOLED_ALIAS, TenantScope
from infrastructure.persistence.findings.models import Finding

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_RECOMPUTE = "components.findings.infrastructure.tasks.finding_risk_tasks.recompute_finding_risk"
_SCOPES = "components.shared_platform.application.providers.tenancy_scopes_provider.scheduled_sweep_scopes"


def _event() -> VulnIntelRefreshed:
    return VulnIntelRefreshed(epss_score_date="2026-08-19", kev_catalog_version="2026.08.19")


def _finding(ws, uid):
    now = timezone.now()
    return Finding.objects.create(
        workspace=ws,
        source="cloud_posture.prowler",
        fingerprint=uid,
        title=f"finding {uid}",
        severity="high",
        status="open",
        first_seen_at=now,
        last_seen_at=now,
    )


@pytest.fixture
def _one_scope():
    """The suite runs on ONE SQLite database, so every scope resolves to it.

    That is enough to prove what matters here — that the handler ITERATES the
    scope list and binds each one — without pretending the test harness has four
    databases. The real routing is proven on the cluster (see the module
    docstring); what a test can regress is the iteration, and that is what this
    asserts."""
    return [
        TenantScope(label="pooled", db_alias=POOLED_ALIAS),
        TenantScope(label="acme", db_alias=POOLED_ALIAS),
    ]


def test_the_handler_visits_every_tenant_scope(workspace_factory, _one_scope):
    """The regression that matters: one scope visited = dedicated tenants frozen."""
    ws = workspace_factory()
    _finding(ws, "f-1")
    visited = []

    real_bind = TenantScope.bind

    def _tracking_bind(self):
        visited.append(self.label)
        return real_bind(self)

    with (
        patch(_SCOPES, return_value=_one_scope),
        patch.object(TenantScope, "bind", _tracking_bind),
        patch(_RECOMPUTE),
    ):
        rescore_all_workspaces_on_feed_refresh(_event())

    assert visited == ["pooled", "acme"], "the handler did not fan out across tenants"


def test_every_workspace_with_findings_is_enqueued_per_scope(workspace_factory, _one_scope):
    ws = workspace_factory()
    _finding(ws, "f-1")

    with patch(_SCOPES, return_value=_one_scope), patch(_RECOMPUTE) as recompute:
        rescore_all_workspaces_on_feed_refresh(_event())

    # One workspace with findings, visible from both scopes in this single-DB
    # harness → one enqueue per scope.
    assert recompute.apply_async.call_count == 2
    assert {c.kwargs["kwargs"]["workspace_id"] for c in recompute.apply_async.call_args_list} == {str(ws.id)}


def test_the_enqueue_happens_with_that_tenant_bound(workspace_factory, _one_scope):
    """The dispatch must carry the scope's tenancy headers, or the worker
    rescores the wrong database."""
    from components.shared_platform.infrastructure.tenancy.context import get_current_tenant

    ws = workspace_factory()
    _finding(ws, "f-1")
    bound_at_dispatch = []

    with patch(_SCOPES, return_value=_one_scope), patch(_RECOMPUTE) as recompute:
        recompute.apply_async.side_effect = lambda **_: bound_at_dispatch.append(get_current_tenant())
        rescore_all_workspaces_on_feed_refresh(_event())

    assert len(bound_at_dispatch) == 2
    assert all(t is not None for t in bound_at_dispatch), "enqueued with no tenant bound"


def test_one_unreachable_tenant_does_not_stop_the_others(workspace_factory, _one_scope, caplog):
    """A dedicated database that is down must not freeze the whole fleet's
    scores against a stale snapshot."""
    import logging

    ws = workspace_factory()
    _finding(ws, "f-1")
    real_bind = TenantScope.bind

    def _flaky_bind(self):
        if self.label == "pooled":
            raise RuntimeError("database unreachable")
        return real_bind(self)

    with (
        patch(_SCOPES, return_value=_one_scope),
        patch.object(TenantScope, "bind", _flaky_bind),
        patch(_RECOMPUTE) as recompute,
        caplog.at_level(logging.ERROR),
    ):
        rescore_all_workspaces_on_feed_refresh(_event())

    # The healthy scope still got its rescore.
    assert recompute.apply_async.call_count == 1
    assert any("feed_refresh_scope_failed" in r.message for r in caplog.records)


def test_a_workspace_without_findings_is_not_enqueued(workspace_factory, _one_scope):
    """Nothing to rescore is not a reason to wake the worker."""
    workspace_factory()

    with patch(_SCOPES, return_value=_one_scope), patch(_RECOMPUTE) as recompute:
        rescore_all_workspaces_on_feed_refresh(_event())

    assert recompute.apply_async.call_count == 0
