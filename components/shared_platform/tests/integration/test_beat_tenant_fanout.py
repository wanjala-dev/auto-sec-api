"""Celery Beat binds a tenant — for every scheduled task, and for every tenant.

THE FAILURE STORY these tests pin. Beat dispatches with no request, no host and
no tenant. The fail-closed router (ADR 0029 D4) refuses tenant-routed queries
when nothing is bound, so **every scheduled sweep raised on its first query**.
Confirmed on the live cluster 2026-08-19 — the router registered, four aliases
configured, an unbound ``AwsOrganizationConnection.objects.count()`` raising
``UnboundTenantError`` — with 27 of 28 scheduled tasks in that state, including
``workflow.run_due_schedules``, which fires every minute in every environment.

The second, quieter half: binding each sweep to the pooled console would have
stopped the crash while leaving dedicated-tier tenants unswept — their sessions
never expired, their workflows never run, their cloud accounts never scanned —
with every log line reading "completed". So the fix fans out across every tenant
rather than pinning to the pool, and these tests assert both halves.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from components.shared_platform.infrastructure.tasks.tenancy_fanout_tasks import (
    MODE_SHARED,
    run_for_each_tenant,
)
from components.shared_platform.infrastructure.tenancy.sweep import (
    POOLED_ALIAS,
    POOLED_LABEL,
    TenantScope,
    sweep_scopes,
)
from infrastructure.persistence.tenancy.models import Tenant

_TARGET = "cloud_posture.schedule_prowler_runs"


@contextmanager
def _registered_as(name, task):
    """Add ``task`` to the LIVE Celery registry under ``name`` for the block.

    Additive rather than replacing the registry wholesale: the fan-out task is
    itself registered there, and Celery resolves a task's own name through the
    registry when it is called, so clearing it breaks the thing under test.
    """
    from celery import current_app

    with patch.dict(current_app.tasks, {name: task}):
        yield


def _tenant(subdomain, *, mode="dedicated", alias=None, active=True):
    return Tenant.objects.create(
        subdomain=subdomain,
        name=subdomain.title(),
        isolation_mode=mode,
        db_alias=alias if alias is not None else (f"tenant_{subdomain}" if mode == "dedicated" else ""),
        is_active=active,
    )


@pytest.mark.integration
@pytest.mark.django_db
class TestSweepScopes:
    def test_the_pool_is_always_swept_and_always_first(self):
        """Most customers live in the pool (tenancy skill §2a), so a failure
        later in the list must not be what stops the pool being swept."""
        scopes = sweep_scopes()

        assert scopes[0] == TenantScope(label=POOLED_LABEL, db_alias=POOLED_ALIAS)

    def test_every_active_dedicated_tenant_is_swept(self, settings):
        settings.DATABASES = {**settings.DATABASES, "tenant_acme": settings.DATABASES["default"]}
        _tenant("acme")

        labels = [s.label for s in sweep_scopes()]

        assert labels == [POOLED_LABEL, "acme"]

    def test_an_inactive_tenant_is_not_swept(self, settings):
        """Deactivation 404s at the middleware; it would be incoherent for
        background work to keep operating on that customer."""
        settings.DATABASES = {**settings.DATABASES, "tenant_gone": settings.DATABASES["default"]}
        _tenant("gone", active=False)

        assert [s.label for s in sweep_scopes()] == [POOLED_LABEL]

    def test_a_pooled_tenant_does_not_add_a_second_default_scope(self):
        """A pooled tenant shares ``default`` — sweeping it again would run every
        scheduled task twice against the same rows."""
        _tenant("senso", mode="pooled")

        assert [s.db_alias for s in sweep_scopes()] == [POOLED_ALIAS]

    def test_a_registry_row_without_a_deployed_alias_is_skipped_loudly(self, settings, caplog):
        """Registry row before deploy config is the documented provisioning
        order (skill §8 step 2). One half-provisioned tenant must not break the
        fleet's sweep — but it must not vanish silently either."""
        import logging

        _tenant("notdeployed", alias="tenant_notdeployed")

        with caplog.at_level(logging.WARNING):
            labels = [s.label for s in sweep_scopes()]

        assert labels == [POOLED_LABEL]
        assert any("tenant_sweep_scope_skipped" in r.message for r in caplog.records)


@pytest.mark.integration
@pytest.mark.django_db
class TestScopeBinding:
    def test_binding_a_scope_sets_and_clears_the_tenant(self):
        from components.shared_platform.infrastructure.tenancy.context import (
            KIND_DEDICATED,
            get_current_tenant,
        )

        scope = TenantScope(label="acme", db_alias="tenant_acme")
        with scope.bind():
            bound = get_current_tenant()
            assert bound is not None
            assert bound.kind == KIND_DEDICATED
            assert bound.db_alias == "tenant_acme"
            assert bound.subdomain == "acme"

    def test_the_pooled_scope_binds_pooled_not_dedicated(self):
        from components.shared_platform.infrastructure.tenancy.context import (
            KIND_POOLED,
            get_current_tenant,
        )

        with TenantScope(label=POOLED_LABEL, db_alias=POOLED_ALIAS).bind():
            assert get_current_tenant().kind == KIND_POOLED

    @pytest.mark.unbound_tenancy
    def test_the_binding_is_released_even_when_the_body_raises(self):
        """A sweep that raised without unbinding would leave the next tenant's
        dispatch stamped with the previous customer."""
        from components.shared_platform.infrastructure.tenancy.context import get_current_tenant

        with pytest.raises(RuntimeError), TenantScope(label="acme", db_alias="tenant_acme").bind():
            raise RuntimeError("boom")

        assert get_current_tenant() is None


@pytest.mark.integration
@pytest.mark.django_db
class TestFanOut:
    def _run(self, **kwargs):
        return run_for_each_tenant(**kwargs)

    def test_the_target_is_dispatched_once_per_tenant(self, settings):
        settings.DATABASES = {
            **settings.DATABASES,
            "tenant_acme": settings.DATABASES["default"],
            "tenant_beta": settings.DATABASES["default"],
        }
        _tenant("acme")
        _tenant("beta")
        target = MagicMock()

        with _registered_as(_TARGET, target):
            result = self._run(task=_TARGET)

        assert target.apply_async.call_count == 3  # pooled + acme + beta
        assert result["scopes"] == 3
        assert result["dispatched"] == 3
        assert result["success"] is True

    def test_each_dispatch_happens_with_that_tenant_bound(self, settings):
        """This is the whole mechanism: publishing inside the binding is what
        makes ``before_task_publish`` stamp the tenancy headers, which is what
        makes ``task_prerun`` bind them in the worker."""
        from components.shared_platform.infrastructure.tenancy.context import get_current_tenant

        settings.DATABASES = {**settings.DATABASES, "tenant_acme": settings.DATABASES["default"]}
        _tenant("acme")
        seen = []
        target = MagicMock()
        target.apply_async.side_effect = lambda **_: seen.append(get_current_tenant())

        with _registered_as(_TARGET, target):
            self._run(task=_TARGET)

        assert [t.db_alias for t in seen] == [None, "tenant_acme"]

    def test_one_tenants_failure_does_not_stop_the_others(self, settings):
        settings.DATABASES = {
            **settings.DATABASES,
            "tenant_acme": settings.DATABASES["default"],
            "tenant_beta": settings.DATABASES["default"],
        }
        _tenant("acme")
        _tenant("beta")
        target = MagicMock()
        calls = {"n": 0}

        def _flaky(**_):
            calls["n"] += 1
            if calls["n"] == 2:  # the acme dispatch
                raise RuntimeError("broker refused")

        target.apply_async.side_effect = _flaky

        with _registered_as(_TARGET, target):
            result = self._run(task=_TARGET)

        assert result["dispatched"] == 2
        assert result["failed"] == 1
        assert result["success"] is False

    def test_shared_mode_runs_once_against_the_pool(self, settings):
        """Global reference data (EPSS ~280k rows, identical for everyone) routes
        to ``default`` whoever is bound — fanning it out would re-download and
        rewrite the same snapshot once per tenant, growing with the customer
        count. Still BOUND, so its downstream domain events carry a header."""
        settings.DATABASES = {**settings.DATABASES, "tenant_acme": settings.DATABASES["default"]}
        _tenant("acme")
        target = MagicMock()

        with _registered_as("vuln_intel.refresh_feeds", target):
            result = self._run(task="vuln_intel.refresh_feeds", mode=MODE_SHARED)

        assert target.apply_async.call_count == 1
        assert result["scopes"] == 1

    def test_extra_kwargs_are_forwarded_to_the_target(self):
        target = MagicMock()

        with _registered_as(_TARGET, target):
            self._run(task=_TARGET, kwargs={"wave": 3})

        assert target.apply_async.call_args.kwargs["kwargs"] == {"wave": 3}

    def test_an_unregistered_target_fails_loudly_instead_of_silently(self, caplog):
        """A beat entry naming a task nobody registered is a dead schedule — the
        exact failure class the beat-registration guard exists to prevent."""
        import logging

        with caplog.at_level(logging.ERROR):
            result = self._run(task="nope.does_not_exist")

        assert result["success"] is False
        assert result["error"] == "unknown_task"
        assert any("unknown_task" in r.message for r in caplog.records)
