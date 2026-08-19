"""Scheduled re-discovery of AWS Organization member accounts (task #155, gap 1).

THE FAILURE STORY these tests pin:

``verify_and_discover`` ran on manual verify only. The CloudFormation StackSet we
hand the customer has ``AutoDeployment`` on, so when a new account joins their
Organization the audit role lands in it correctly — and we never call
``organizations:ListAccounts`` again, so no ``AwsAccountLink`` row is ever
created, the scan fan-out never sees it, and the connection keeps reading
CONNECTED. Silent coverage loss: the customer believes the org is covered, the
new account has never been scanned, and nothing anywhere says so.

The reconciliation rules asserted here (the table also lives in the repository
docstring — this file is its executable form):

| existing link | seen ACTIVE in the org  | absent from the ACTIVE set |
|---------------|-------------------------|----------------------------|
| (none)        | create DISCOVERED       | —                          |
| DISCOVERED    | DISCOVERED (name kept fresh) | SUSPENDED             |
| VERIFIED      | VERIFIED (untouched)    | SUSPENDED                  |
| SUSPENDED     | DISCOVERED (it came back) | SUSPENDED                |
| FAILED        | FAILED — scheduled discovery never clears a health verdict; an OPERATOR verify does | SUSPENDED |
| EXCLUDED      | EXCLUDED — ALWAYS       | EXCLUDED — ALWAYS          |

Plus the guard that keeps a degraded discovery response from nuking an org:
absence only means SUSPENDED when the organization was actually walked
(``org_walked``). A denied ``describe_organization``/``list_accounts`` returns
just the management account, and treating that as "everything else is gone"
would suspend an entire org on a transient permission blip.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from infrastructure.persistence.integrations.models import (
    AwsAccountLink,
    AwsOrganizationConnection,
)

_MGMT = "111111111111"
_STS_ADAPTER = "components.integrations.infrastructure.adapters.sts_org_adapter.StsOrgAdapter"


def _conn(ws, *, org_wide=True, status=AwsOrganizationConnection.Status.CONNECTED):
    return AwsOrganizationConnection.objects.create(
        workspace=ws,
        management_account_id=_MGMT,
        external_id=f"ext-{uuid.uuid4().hex[:12]}",
        role_name="AcmeAuditRole",
        org_wide=org_wide,
        status=status,
    )


def _link(conn, account_id, status, name=""):
    return AwsAccountLink.objects.create(connection=conn, account_id=account_id, status=status, account_name=name)


def _discovery(accounts, *, org_walked=True, organization_id="o-acme"):
    """The ``OrgVerificationPort`` result shape for a successful walk."""
    return {
        "organization_id": organization_id,
        "accounts": [{"id": a, "name": f"acct-{a}"} for a in accounts],
        "org_walked": org_walked,
    }


def _status_of(conn, account_id) -> str:
    return AwsAccountLink.objects.get(connection=conn, account_id=account_id).status


@pytest.mark.integration
@pytest.mark.django_db
class TestReconciliationRules:
    """The status transition table, one test per row."""

    def _reconcile(self, conn, accounts, *, org_walked=True, clear_failed=False):
        from components.integrations.infrastructure.repositories.aws_connection_repository import (
            AwsConnectionRepository,
        )

        return AwsConnectionRepository().reconcile_accounts(
            conn,
            accounts=_discovery(accounts, org_walked=org_walked)["accounts"],
            org_walked=org_walked,
            clear_failed=clear_failed,
        )

    def test_a_new_account_is_created_as_discovered(self, workspace_factory):
        conn = _conn(workspace_factory())
        _link(conn, _MGMT, AwsAccountLink.Status.VERIFIED)

        counts = self._reconcile(conn, [_MGMT, "222222222222"])

        assert _status_of(conn, "222222222222") == AwsAccountLink.Status.DISCOVERED
        assert counts["created"] == 1

    def test_a_verified_account_stays_verified(self, workspace_factory):
        conn = _conn(workspace_factory())
        _link(conn, _MGMT, AwsAccountLink.Status.VERIFIED)

        self._reconcile(conn, [_MGMT])

        assert _status_of(conn, _MGMT) == AwsAccountLink.Status.VERIFIED

    def test_an_account_gone_from_the_org_is_suspended_not_deleted(self, workspace_factory):
        conn = _conn(workspace_factory())
        _link(conn, _MGMT, AwsAccountLink.Status.VERIFIED)
        _link(conn, "333333333333", AwsAccountLink.Status.VERIFIED)

        counts = self._reconcile(conn, [_MGMT])

        # History and provenance matter — the row survives, the status tells the story.
        assert _status_of(conn, "333333333333") == AwsAccountLink.Status.SUSPENDED
        assert counts["suspended"] == 1

    def test_a_returning_account_goes_back_to_discovered(self, workspace_factory):
        conn = _conn(workspace_factory())
        _link(conn, "444444444444", AwsAccountLink.Status.SUSPENDED)

        counts = self._reconcile(conn, ["444444444444"])

        assert _status_of(conn, "444444444444") == AwsAccountLink.Status.DISCOVERED
        assert counts["reactivated"] == 1

    def test_excluded_is_never_clobbered_by_discovery(self, workspace_factory):
        """THE TRAP. An operator excluded this account; discovery sees it ACTIVE
        and must not silently put it back in the scan fan-out."""
        conn = _conn(workspace_factory())
        _link(conn, "555555555555", AwsAccountLink.Status.EXCLUDED)

        counts = self._reconcile(conn, ["555555555555"])

        assert _status_of(conn, "555555555555") == AwsAccountLink.Status.EXCLUDED
        assert counts["protected"] == 1

    def test_excluded_survives_even_when_the_account_leaves_the_org(self, workspace_factory):
        conn = _conn(workspace_factory())
        _link(conn, "555555555555", AwsAccountLink.Status.EXCLUDED)

        self._reconcile(conn, [_MGMT])

        assert _status_of(conn, "555555555555") == AwsAccountLink.Status.EXCLUDED

    def test_excluded_is_never_clobbered_by_an_operator_verify_either(self, workspace_factory):
        """``clear_failed=True`` is the operator-verify mode; it clears a health
        verdict, never an intent."""
        conn = _conn(workspace_factory())
        _link(conn, "555555555555", AwsAccountLink.Status.EXCLUDED)

        self._reconcile(conn, ["555555555555"], clear_failed=True)

        assert _status_of(conn, "555555555555") == AwsAccountLink.Status.EXCLUDED

    def test_scheduled_discovery_does_not_resurrect_a_failed_link(self, workspace_factory):
        """FAILED is a verdict about OUR role access. Discovery only proves org
        membership, so it must not silently claim the account is healthy again —
        it would flap FAILED → DISCOVERED → scan → FAILED every sweep."""
        conn = _conn(workspace_factory())
        _link(conn, "666666666666", AwsAccountLink.Status.FAILED)

        self._reconcile(conn, ["666666666666"], clear_failed=False)

        assert _status_of(conn, "666666666666") == AwsAccountLink.Status.FAILED

    def test_an_operator_verify_does_clear_a_failed_link(self, workspace_factory):
        """A human pressing Verify is explicitly asking us to re-test access —
        that IS the sanctioned recovery path out of FAILED."""
        conn = _conn(workspace_factory())
        _link(conn, "666666666666", AwsAccountLink.Status.FAILED)

        self._reconcile(conn, ["666666666666"], clear_failed=True)

        assert _status_of(conn, "666666666666") == AwsAccountLink.Status.DISCOVERED

    def test_a_failed_account_that_left_the_org_is_suspended(self, workspace_factory):
        """Org absence is a newer, stronger fact than a stale access verdict."""
        conn = _conn(workspace_factory())
        _link(conn, "666666666666", AwsAccountLink.Status.FAILED)

        self._reconcile(conn, [_MGMT])

        assert _status_of(conn, "666666666666") == AwsAccountLink.Status.SUSPENDED

    def test_a_degraded_walk_never_suspends_the_org(self, workspace_factory):
        """``describe_organization``/``list_accounts`` denied → the adapter returns
        only the management account. Treating that as "everyone else is gone"
        would suspend an entire customer org on a permission blip."""
        conn = _conn(workspace_factory())
        _link(conn, _MGMT, AwsAccountLink.Status.VERIFIED)
        _link(conn, "777777777777", AwsAccountLink.Status.VERIFIED)

        counts = self._reconcile(conn, [_MGMT], org_walked=False)

        assert _status_of(conn, "777777777777") == AwsAccountLink.Status.VERIFIED
        assert counts["suspended"] == 0

    def test_the_account_name_is_refreshed_without_touching_status(self, workspace_factory):
        conn = _conn(workspace_factory())
        _link(conn, "888888888888", AwsAccountLink.Status.VERIFIED, name="old-name")

        self._reconcile(conn, ["888888888888"])

        link = AwsAccountLink.objects.get(connection=conn, account_id="888888888888")
        assert link.account_name == "acct-888888888888"
        assert link.status == AwsAccountLink.Status.VERIFIED


@pytest.mark.integration
@pytest.mark.django_db
class TestScheduledRediscoverySweep:
    """The beat task — the thing whose absence WAS the gap."""

    def _run(self):
        from components.integrations.infrastructure.tasks.aws_discovery_tasks import (
            rediscover_aws_org_accounts,
        )

        return rediscover_aws_org_accounts()

    def test_a_new_org_account_is_discovered_without_any_operator_action(self, workspace_factory):
        """The headline gap: nobody touches the UI, the account still shows up."""
        conn = _conn(workspace_factory())
        _link(conn, _MGMT, AwsAccountLink.Status.VERIFIED)

        with patch(
            f"{_STS_ADAPTER}.verify_and_discover",
            return_value=_discovery([_MGMT, "999999999999"]),
        ):
            result = self._run()

        assert _status_of(conn, "999999999999") == AwsAccountLink.Status.DISCOVERED
        assert result["connections"] == 1
        assert result["created"] == 1
        assert result["failed"] == 0

    def test_the_sweep_only_touches_connected_org_wide_connections(self, workspace_factory):
        """A PENDING connection has no working role yet; a single-account one has
        no organization to walk. Calling either every hour is pure waste."""
        ws = workspace_factory()
        _conn(ws, status=AwsOrganizationConnection.Status.PENDING)
        AwsOrganizationConnection.objects.create(
            workspace=ws,
            management_account_id="222222222222",
            external_id=f"ext-{uuid.uuid4().hex[:12]}",
            org_wide=False,
            status=AwsOrganizationConnection.Status.CONNECTED,
        )

        with patch(f"{_STS_ADAPTER}.verify_and_discover") as verifier:
            result = self._run()

        assert verifier.call_count == 0
        assert result["connections"] == 0

    def test_one_broken_org_does_not_abort_everyone_elses_sweep(self, workspace_factory):
        """A single customer whose role was revoked must not stop re-discovery
        for every other customer in the fleet."""
        broken = _conn(workspace_factory())
        healthy = _conn(workspace_factory())
        _link(healthy, _MGMT, AwsAccountLink.Status.VERIFIED)

        def _side_effect(*, management_account_id, role_name, external_id, discover=True):
            if external_id == broken.external_id:
                raise RuntimeError("AccessDenied: role revoked")
            return _discovery([_MGMT, "101010101010"])

        with patch(f"{_STS_ADAPTER}.verify_and_discover", side_effect=_side_effect):
            result = self._run()

        assert _status_of(healthy, "101010101010") == AwsAccountLink.Status.DISCOVERED
        assert result["failed"] == 1
        assert result["connections"] == 2

    def test_a_failing_connection_is_not_marked_error_by_a_background_sweep(self, workspace_factory):
        """Re-discovery is a read. A transient Organizations blip must not flip a
        working connection to ERROR and light up the operator's HUD."""
        conn = _conn(workspace_factory())

        with patch(f"{_STS_ADAPTER}.verify_and_discover", side_effect=RuntimeError("throttled")):
            self._run()

        conn.refresh_from_db()
        assert conn.status == AwsOrganizationConnection.Status.CONNECTED

    def test_the_sweep_is_idempotent(self, workspace_factory):
        conn = _conn(workspace_factory())
        _link(conn, _MGMT, AwsAccountLink.Status.VERIFIED)

        with patch(
            f"{_STS_ADAPTER}.verify_and_discover",
            return_value=_discovery([_MGMT, "121212121212"]),
        ):
            self._run()
            second = self._run()

        assert AwsAccountLink.objects.filter(connection=conn).count() == 2
        assert second["created"] == 0
        assert _status_of(conn, _MGMT) == AwsAccountLink.Status.VERIFIED

    @pytest.mark.unbound_tenancy
    def test_the_sweep_binds_a_tenant_rather_than_inheriting_one(self, workspace_factory):
        """Tenancy skill §3i: a beat task arrives with nothing bound, and the
        fail-closed router refuses unbound queries. Binding must be explicit —
        'whatever the last task on this prefork child left' is a cross-tenant read.

        ``unbound_tenancy`` opts out of the suite's pooled auto-bind, so this is
        the real thing: if the task did not bind, nothing would be bound."""
        from components.shared_platform.infrastructure.tenancy.context import (
            KIND_POOLED,
            get_current_tenant,
        )

        conn = _conn(workspace_factory())
        _link(conn, _MGMT, AwsAccountLink.Status.VERIFIED)
        seen: list = []

        def _capture(**_kwargs):
            seen.append(get_current_tenant())
            return _discovery([_MGMT])

        with patch(f"{_STS_ADAPTER}.verify_and_discover", side_effect=_capture):
            self._run()

        assert seen and seen[0] is not None, "the sweep queried with no tenant bound"
        assert seen[0].kind == KIND_POOLED


@pytest.mark.integration
@pytest.mark.django_db
class TestOperatorVerifyUsesTheSameReconciliation:
    """DRY: one reconciliation path, so the two callers can never drift.

    Before this change ``mark_connected`` blanket-upserted every discovered
    account to DISCOVERED — which silently destroyed an operator's EXCLUDED
    intent on every re-verify.
    """

    def test_verify_no_longer_wipes_an_operator_exclusion(self, workspace_factory):
        from components.integrations.application.providers.aws_connection_provider import (
            get_aws_connection_service,
        )

        conn = _conn(workspace_factory())
        _link(conn, "131313131313", AwsAccountLink.Status.EXCLUDED)

        with patch(
            f"{_STS_ADAPTER}.verify_and_discover",
            return_value=_discovery([_MGMT, "131313131313"]),
        ):
            get_aws_connection_service().verify_connection(conn)

        assert _status_of(conn, "131313131313") == AwsAccountLink.Status.EXCLUDED
        conn.refresh_from_db()
        assert conn.status == AwsOrganizationConnection.Status.CONNECTED


@pytest.mark.unit
class TestTheAdapterReportsWhetherItWalkedTheOrg:
    """``org_walked`` is the fact that keeps a denied walk from suspending an org."""

    _CREDS_PROVIDER = "components.integrations.application.providers.aws_credentials_provider.get_aws_credentials_port"
    _CREDS = {"AccessKeyId": "AK", "SecretAccessKey": "s", "SessionToken": "t"}

    def test_single_account_verification_reports_no_walk(self):
        from unittest.mock import MagicMock

        from components.integrations.infrastructure.adapters.sts_org_adapter import StsOrgAdapter

        port = MagicMock()
        port.assume_role.return_value = self._CREDS
        with patch(self._CREDS_PROVIDER, return_value=port):
            result = StsOrgAdapter().verify_and_discover(
                management_account_id=_MGMT,
                role_name="AcmeAuditRole",
                external_id="ext",
                discover=False,
            )

        assert result["org_walked"] is False
        assert result["accounts"] == [{"id": _MGMT, "name": ""}]
