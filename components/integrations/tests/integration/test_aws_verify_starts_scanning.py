"""Verifying an AWS connection starts the first scan (task #155, gap 3).

THE FAILURE STORY these tests pin:

``verify_and_discover`` succeeding dispatched nothing. The connect wizard's final
step was a MANUAL "Scan" button, so an operator who connected their org and
closed the tab saw an empty product until the nightly beat at 02:00 — no error,
no spinner, no signal that nothing had started. Same silent class as the
discovery gap and the unbounded fan-out: the customer's belief and the product's
behaviour diverge, and nothing says so.

Connecting a source now starts scanning it, through the SAME dispatch seam the
"Scan now" endpoint and the beat scheduler use — so the cooldown, the
one-in-flight invariant and the global concurrency cap all apply unchanged.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from infrastructure.persistence.integrations.models import (
    AwsAccountLink,
    AwsOrganizationConnection,
)
from infrastructure.persistence.scanning.models import ScanRun

_MGMT = "123456789012"
_MEMBER = "210987654321"
_SOURCE = "cloud_posture.prowler"
_STS_ADAPTER = "components.integrations.infrastructure.adapters.sts_org_adapter.StsOrgAdapter"
_DISPATCH = "components.scanning.application.providers.scan_dispatch_provider.dispatch_scan"


def _conn(ws, **overrides):
    defaults = {
        "workspace": ws,
        "management_account_id": _MGMT,
        "external_id": f"ext-{uuid.uuid4().hex[:12]}",
        "role_name": "AcmeAuditRole",
        "org_wide": True,
    }
    defaults.update(overrides)
    return AwsOrganizationConnection.objects.create(**defaults)


def _discovery(accounts):
    return {
        "organization_id": "o-acme",
        "accounts": [{"id": a, "name": f"acct-{a}"} for a in accounts],
        "org_walked": True,
    }


@pytest.mark.integration
@pytest.mark.django_db
class TestVerifyDispatchesTheFirstScan:
    def _verify(self, conn, accounts, capture):
        from components.integrations.application.providers.aws_connection_provider import (
            get_aws_connection_service,
        )

        with (
            patch(f"{_STS_ADAPTER}.verify_and_discover", return_value=_discovery(accounts)),
            capture(execute=True),
        ):
            return get_aws_connection_service().verify_and_scan(conn)

    def test_verifying_scans_every_discovered_account(self, workspace_factory, django_capture_on_commit_callbacks):
        conn = _conn(workspace_factory())

        with patch(_DISPATCH) as m_dispatch:
            _, scans = self._verify(conn, [_MGMT, _MEMBER], django_capture_on_commit_callbacks)

        assert m_dispatch.call_count == 2
        assert {c.kwargs["account_id"] for c in m_dispatch.call_args_list} == {_MGMT, _MEMBER}
        assert scans["enqueued"] == 2
        assert scans["scannable"] == 2

    def test_the_scan_is_stamped_with_verify_provenance(self, workspace_factory, django_capture_on_commit_callbacks):
        """A run started by connecting is neither an operator's Scan-now nor the
        beat — the run history has to be able to answer "did connecting actually
        start anything?"."""
        conn = _conn(workspace_factory())

        with patch(_DISPATCH) as m_dispatch:
            self._verify(conn, [_MGMT], django_capture_on_commit_callbacks)

        assert m_dispatch.call_args.kwargs["trigger"] == "verify"

    def test_the_dispatch_happens_after_the_account_links_commit(self, workspace_factory):
        """The fan-out reads the AwsAccountLink rows the verification writes, and
        the Celery worker reads them back over its OWN connection. Enqueueing
        inside the transaction races its own write."""
        from components.integrations.application.providers.aws_connection_provider import (
            get_aws_connection_service,
        )

        conn = _conn(workspace_factory())

        with (
            patch(f"{_STS_ADAPTER}.verify_and_discover", return_value=_discovery([_MGMT])),
            patch(_DISPATCH) as m_dispatch,
        ):
            # No on-commit capture: inside the test's transaction the callback
            # must NOT have fired yet.
            get_aws_connection_service().verify_and_scan(conn)
            assert m_dispatch.call_count == 0, "dispatched before the verify write committed"

    def test_re_verifying_does_not_stack_a_second_scan(self, workspace_factory, django_capture_on_commit_callbacks):
        """Operators re-run verify. The per-account cooldown / one-in-flight gate
        must absorb it — asserted, not assumed."""
        conn = _conn(workspace_factory())

        with patch(_DISPATCH) as first:
            self._verify(conn, [_MGMT], django_capture_on_commit_callbacks)
        # The first dispatch left a PENDING ScanRun; the gate sees it in flight.
        ScanRun.objects.create(
            workspace=conn.workspace,
            source=_SOURCE,
            target_ref=_MGMT,
            status=ScanRun.Status.PENDING,
        )

        with patch(_DISPATCH) as second:
            _, scans = self._verify(conn, [_MGMT], django_capture_on_commit_callbacks)

        assert first.call_count == 1
        assert second.call_count == 0
        assert scans["enqueued"] == 0
        assert scans["blocked"] == 1

    def test_a_large_org_defers_the_overflow_instead_of_stampeding(
        self, workspace_factory, django_capture_on_commit_callbacks, settings
    ):
        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 2
        conn = _conn(workspace_factory())
        accounts = [f"{i:012d}" for i in range(6)]

        with patch(_DISPATCH) as m_dispatch:
            _, scans = self._verify(conn, accounts, django_capture_on_commit_callbacks)

        assert m_dispatch.call_count == 2
        assert scans["enqueued"] == 2
        assert scans["deferred"] == 4
        assert scans["retry_after"] > 0

    def test_a_dispatch_failure_never_fails_the_verification(
        self, workspace_factory, django_capture_on_commit_callbacks, caplog
    ):
        """The connection IS verified either way; the nightly sweep is the retry."""
        import logging

        conn = _conn(workspace_factory())

        with patch(_DISPATCH, side_effect=RuntimeError("broker down")), caplog.at_level(logging.ERROR):
            verified, _ = self._verify(conn, [_MGMT], django_capture_on_commit_callbacks)

        verified.refresh_from_db()
        assert verified.status == AwsOrganizationConnection.Status.CONNECTED
        assert any("autoscan_dispatch_failed" in r.message for r in caplog.records)


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
class TestVerifyReportsWhatItStarted:
    """The FE contract — asserted on the REAL request path, not a simulation.

    ``transaction=True`` matters here and is not incidental. A normal
    ``django_db`` test wraps everything in a transaction that never commits, so
    ``transaction.on_commit`` defers and the counts are not yet known when the
    response is built — which is exactly the state the port's ``settled`` flag
    describes. A real request runs in autocommit (no ``ATOMIC_REQUESTS``), the
    callback fires inline, and the counts ARE final. Only a transactional test
    reproduces that, so only a transactional test may assert the numbers the
    wizard will actually render.
    """

    def test_nothing_scannable_reports_none_rather_than_a_hollow_zero(self, workspace_factory):
        """Verified with no accounts is a legitimate state. Say so; do not report
        "0 scans enqueued", which reads as a failure."""
        from components.integrations.application.providers.aws_connection_provider import (
            get_aws_connection_service,
        )

        conn = _conn(workspace_factory())
        # Discovery returns the management account, but the operator excluded it.
        AwsAccountLink.objects.create(connection=conn, account_id=_MGMT, status=AwsAccountLink.Status.EXCLUDED)

        with (
            patch(f"{_STS_ADAPTER}.verify_and_discover", return_value=_discovery([_MGMT])),
            patch(_DISPATCH) as m_dispatch,
        ):
            _, scans = get_aws_connection_service().verify_and_scan(conn)

        assert m_dispatch.call_count == 0
        assert scans is None

    def test_the_verify_response_reports_what_it_started(self, api_client, workspace_factory):
        ws = workspace_factory()
        api_client.force_authenticate(ws.workspace_owner)
        conn = _conn(ws)

        with (
            patch(f"{_STS_ADAPTER}.verify_and_discover", return_value=_discovery([_MGMT, _MEMBER])),
            patch(_DISPATCH),
        ):
            resp = api_client.post(f"/integrations/workspaces/{ws.id}/aws/{conn.id}/verify/")

        assert resp.status_code == 200, resp.data
        assert resp.data["success"] is True
        assert resp.data["scans"] == {
            "scannable": 2,
            "enqueued": 2,
            "deferred": 0,
            "blocked": 0,
            "retry_after": None,
        }

    def test_a_failed_verification_still_502s_and_reports_no_scans(self, api_client, workspace_factory):
        ws = workspace_factory()
        api_client.force_authenticate(ws.workspace_owner)
        conn = _conn(ws)

        with patch(f"{_STS_ADAPTER}.verify_and_discover", side_effect=RuntimeError("AccessDenied")):
            resp = api_client.post(f"/integrations/workspaces/{ws.id}/aws/{conn.id}/verify/")

        assert resp.status_code == 502, resp.data
        assert "scans" not in resp.data
