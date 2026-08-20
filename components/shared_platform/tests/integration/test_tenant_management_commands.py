"""``manage.py`` can reach a tenant that is not the pool — and never the wrong one.

THE FAILURE STORY these tests pin. ``run_management_command`` bound the pooled
tenant unconditionally, with no way to opt out, so a dedicated tenant's database
was unreachable by every one of the ~99 management commands: no backfill, no
seed, no data fix, ever. Proven on 2026-08-19 — ``reindex_workspaces --all
--sync --force`` took the pooled database to 0 NULL embeddings of 88 while
``tenant_faura`` (4 of 4) and ``tenant_wanjala`` (6 of 6) were untouched, because
the command never saw those databases. It reported success. Their RAG search
returned zero hits and raised nothing.

The fix adds ``--tenant`` / ``--all-tenants``. The tests below are mostly about
the ways that fix could be WORSE than the gap it closes: a flag that silently
resolves to the pool when it cannot find the tenant is a cross-tenant write, and
that is strictly more dangerous than a tenant you simply cannot reach.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from components.shared_platform.infrastructure.tenancy.context import (
    KIND_DEDICATED,
    KIND_POOLED,
    get_current_tenant,
)
from components.shared_platform.infrastructure.tenancy.management import (
    TenantSelectionError,
    run_management_command,
    scope_for_subdomain,
)
from components.shared_platform.infrastructure.tenancy.workspace_context import (
    get_current_workspace,
)
from infrastructure.persistence.tenancy.models import Tenant

#: A real second sqlite database in the test settings — deliberately NOT a
#: mirror of `default`, so "bound to the tenant" is distinguishable from "bound
#: to the pool" rather than merely asserted.
PROBE_ALIAS = "tenant_probe"


def _dedicated(subdomain: str, *, alias: str = PROBE_ALIAS, active: bool = True) -> Tenant:
    return Tenant.objects.create(
        subdomain=subdomain,
        name=subdomain.title(),
        isolation_mode=KIND_DEDICATED,
        db_alias=alias,
        is_active=active,
    )


def _pooled(subdomain: str, *, workspace_id=None, active: bool = True) -> Tenant:
    return Tenant.objects.create(
        subdomain=subdomain,
        name=subdomain.title(),
        isolation_mode=KIND_POOLED,
        db_alias="",
        workspace_id=workspace_id,
        is_active=active,
    )


class _Recorder:
    """Stands in for ``execute_from_command_line`` and records what was bound.

    The binding is only observable from INSIDE the call — that is the whole
    contract — so the assertions have to be taken there.
    """

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, argv):
        tenant = get_current_tenant()
        self.calls.append(
            {
                "argv": list(argv),
                "kind": tenant.kind if tenant else None,
                "db_alias": tenant.db_alias if tenant else None,
                "subdomain": tenant.subdomain if tenant else "",
                "workspace_id": get_current_workspace(),
            }
        )


@pytest.fixture
def recorder():
    rec = _Recorder()
    with patch("django.core.management.execute_from_command_line", rec):
        yield rec


@pytest.mark.django_db
class TestPooledStaysTheDefault:
    """The load-bearing regression guard: no flag, no change."""

    def test_no_flag_binds_pooled_and_passes_argv_through(self, recorder):
        argv = ["manage.py", "reindex_workspaces", "--all", "--sync"]

        run_management_command(argv)

        assert recorder.calls == [
            {
                "argv": argv,
                "kind": KIND_POOLED,
                "db_alias": None,
                "subdomain": "",
                "workspace_id": None,
            }
        ]

    def test_the_workspace_is_still_left_unbound(self, recorder):
        """Unchanged asymmetry: the database is safe to reach, the rows are not."""
        run_management_command(["manage.py", "migrate"])

        assert recorder.calls[0]["workspace_id"] is None

    @pytest.mark.unbound_tenancy
    def test_nothing_stays_bound_afterwards(self, recorder):
        """``unbound_tenancy``: asserting "nothing bound" is meaningless if the
        autouse fixture bound something first."""
        run_management_command(["manage.py", "migrate"])

        assert get_current_tenant() is None


@pytest.mark.django_db(databases=["default", PROBE_ALIAS])
class TestTenantFlagBindsThatTenantsDatabase:
    def test_a_dedicated_tenant_binds_its_own_alias(self, recorder):
        _dedicated("probe")

        run_management_command(["manage.py", "reindex_workspaces", "--tenant", "probe", "--all"])

        (call,) = recorder.calls
        assert call["kind"] == KIND_DEDICATED
        assert call["db_alias"] == PROBE_ALIAS
        assert call["subdomain"] == "probe"
        # The flag is consumed here; the command must never see it.
        assert call["argv"] == ["manage.py", "reindex_workspaces", "--all"]

    def test_a_dedicated_tenant_binds_no_workspace(self, recorder):
        """The DATABASE is the isolation there; pinning one workspace would
        silently narrow a whole-tenant backfill to a fraction of it."""
        _dedicated("probe")

        run_management_command(["manage.py", "reindex_workspaces", "--tenant", "probe"])

        assert recorder.calls[0]["workspace_id"] is None

    @pytest.mark.unbound_tenancy
    def test_the_binding_is_released_after_the_run(self, recorder):
        """A tenant left bound is the next unit of work's cross-tenant read."""
        _dedicated("probe")

        run_management_command(["manage.py", "migrate", "--tenant", "probe"])

        assert get_current_tenant() is None


@pytest.mark.django_db
class TestPooledTenantsAreScopedByWorkspace:
    """On the shared database the workspace IS the isolation.

    Binding only "pooled" for ``--tenant senso`` would leave the run touching
    every customer in the pool while reading, at the call site, as if it were
    scoped — the same fail-open shape the router refuses.
    """

    def test_a_pooled_tenant_binds_the_workspace_its_registry_row_pins(self, recorder, workspace_factory):
        workspace = workspace_factory(workspace_name="Senso")
        _pooled("senso", workspace_id=workspace.id)

        run_management_command(["manage.py", "reindex_workspaces", "--tenant", "senso"])

        (call,) = recorder.calls
        assert call["kind"] == KIND_POOLED
        assert call["workspace_id"] == str(workspace.id)

    def test_a_pooled_tenant_with_no_workspace_pin_is_refused(self, recorder):
        _pooled("senso", workspace_id=None)

        with pytest.raises(SystemExit) as exit_info:
            run_management_command(["manage.py", "migrate", "--tenant", "senso"])

        assert exit_info.value.code == 1
        assert recorder.calls == [], "the command ran anyway, unscoped, across the whole pool"


@pytest.mark.django_db
class TestUnresolvableTenantsFailClosed:
    """Every one of these has an obvious "helpful" fallback. All of them are
    a write into the wrong customer's data, so all of them stop the run."""

    def test_an_unknown_subdomain_exits_and_never_runs_the_command(self, recorder):
        _dedicated("probe")

        with pytest.raises(SystemExit) as exit_info:
            run_management_command(["manage.py", "migrate", "--tenant", "nope"])

        assert exit_info.value.code == 1
        assert recorder.calls == [], "an unknown tenant fell back to the pooled database"

    def test_an_unknown_subdomain_names_what_it_could_not_find(self):
        with pytest.raises(TenantSelectionError, match="no tenant is registered with subdomain 'nope'"):
            scope_for_subdomain("nope")

    def test_a_deactivated_tenant_is_refused(self):
        _dedicated("gone", active=False)

        with pytest.raises(TenantSelectionError, match="deactivated"):
            scope_for_subdomain("gone")

    def test_a_dedicated_tenant_whose_alias_is_not_deployed_is_refused(self):
        """Registry row before deploy config — the documented provisioning
        ordering. It must not quietly become a pooled run."""
        _dedicated("halfway", alias="tenant_not_in_settings")

        with pytest.raises(TenantSelectionError, match=r"not in settings\.DATABASES"):
            scope_for_subdomain("halfway")

    def test_both_flags_together_exit_without_running(self, recorder):
        with pytest.raises(SystemExit) as exit_info:
            run_management_command(["manage.py", "migrate", "--tenant", "a", "--all-tenants"])

        assert exit_info.value.code == 1
        assert recorder.calls == []


@pytest.mark.django_db(databases=["default", PROBE_ALIAS])
class TestAllTenantsVisitsEveryDatabase:
    def test_it_runs_once_per_scope_pool_first(self, recorder):
        _dedicated("probe")

        run_management_command(["manage.py", "reindex_workspaces", "--all-tenants", "--all"])

        assert [c["kind"] for c in recorder.calls] == [KIND_POOLED, KIND_DEDICATED]
        assert [c["db_alias"] for c in recorder.calls] == [None, PROBE_ALIAS]
        assert all(c["argv"] == ["manage.py", "reindex_workspaces", "--all"] for c in recorder.calls)

    @pytest.mark.unbound_tenancy
    def test_each_scope_is_bound_and_unbound_around_its_own_run(self, recorder):
        """No leak between tenants: the second call must not inherit the first."""
        _dedicated("probe")
        seen_between: list = []

        original = recorder.__call__

        def _spy(argv):
            original(argv)
            seen_between.append(get_current_tenant())

        with patch("django.core.management.execute_from_command_line", _spy):
            run_management_command(["manage.py", "migrate", "--all-tenants"])

        # Each recorded binding is exactly its own scope's — never the previous one.
        assert [t.kind for t in seen_between] == [KIND_POOLED, KIND_DEDICATED]
        assert get_current_tenant() is None

    def test_an_inactive_dedicated_tenant_is_not_visited(self, recorder):
        _dedicated("probe", active=False)

        run_management_command(["manage.py", "migrate", "--all-tenants"])

        assert [c["kind"] for c in recorder.calls] == [KIND_POOLED]
