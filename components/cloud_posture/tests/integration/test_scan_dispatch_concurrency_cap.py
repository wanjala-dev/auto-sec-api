"""Global in-flight cap on the CSPM scan fan-out (task #155, gap 2).

THE FAILURE STORY these tests pin:

``dispatch_connection_scans`` dispatched EVERY scannable account link in one
pass. The per-account gate (cooldown + one-in-flight per target) bounds a single
account; nothing bounded the total. An org with 50-200 accounts therefore fired
50-200 Prowler Jobs at the cluster in one beat tick — each one a 4Gi pod and a
burst of AWS API calls against the same Organizations/STS throttle budget. The
herd either pends forever on cluster capacity or gets throttled by AWS, and both
outcomes look like "the scan failed" rather than "we asked for too much at once".

The fix is a cap with a QUEUE, not a cap with a bin: work over the ceiling is
DEFERRED with a ``retry_after`` and picked up by the next sweep. Returning
"blocked" and walking away would be the same silent-failure class this task
exists to remove — an operator would see 40 scanned out of 200 and no signal
that the other 160 were dropped rather than delayed.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from django.utils import timezone

from components.cloud_posture.infrastructure.services.scan_dispatch_service import (
    dispatch_connection_scans,
)
from infrastructure.persistence.integrations.models import (
    AwsAccountLink,
    AwsOrganizationConnection,
)
from infrastructure.persistence.scanning.models import ScanRun

_SOURCE = "cloud_posture.prowler"
_DISPATCH = "components.scanning.application.providers.scan_dispatch_provider.dispatch_scan"


def _conn(ws):
    return AwsOrganizationConnection.objects.create(
        workspace=ws,
        management_account_id="863183417583",
        external_id=f"ext-{uuid.uuid4().hex[:12]}",
        role_name="AcmeAuditRole",
        status=AwsOrganizationConnection.Status.CONNECTED,
    )


def _links(conn, n):
    return [
        AwsAccountLink.objects.create(
            connection=conn,
            account_id=f"{i:012d}",
            status=AwsAccountLink.Status.DISCOVERED,
        )
        for i in range(n)
    ]


def _dispatched_accounts(mock_dispatch) -> set[str]:
    return {call.kwargs["account_id"] for call in mock_dispatch.call_args_list}


@pytest.mark.integration
@pytest.mark.django_db
class TestGlobalInFlightCap:
    def test_a_large_org_does_not_stampede_the_cluster(self, workspace_factory, settings):
        """N accounts, cap C → exactly C dispatched, N-C deferred, none lost."""
        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 2
        conn = _conn(workspace_factory())
        _links(conn, 5)

        with patch(_DISPATCH) as m_dispatch:
            counts = dispatch_connection_scans(conn, trigger="schedule")

        assert m_dispatch.call_count == 2
        assert counts["enqueued"] == 2
        assert counts["deferred"] == 3
        assert counts["blocked"] == 0
        # Deferral is a promise, not a shrug — it carries when to come back.
        assert counts["retry_after"] is not None and counts["retry_after"] > 0
        # Nothing is lost: every account is accounted for in exactly one bucket.
        assert counts["enqueued"] + counts["deferred"] + counts["blocked"] == 5

    def test_the_next_sweep_picks_up_exactly_what_was_deferred(self, workspace_factory, settings):
        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 2
        conn = _conn(workspace_factory())
        _links(conn, 5)

        with patch(_DISPATCH) as first:
            dispatch_connection_scans(conn, trigger="schedule")
        first_wave = _dispatched_accounts(first)

        # The first wave's scans finished; the cooldown lock is what now holds
        # them back, so the next sweep must reach the ones it deferred.
        with patch(_DISPATCH) as second:
            counts = dispatch_connection_scans(conn, trigger="schedule")
        second_wave = _dispatched_accounts(second)

        assert len(first_wave) == 2
        assert len(second_wave) == 2
        assert not (first_wave & second_wave), "a deferred account was re-dispatched, not queued"
        assert counts["enqueued"] == 2

    def test_running_scans_from_another_workspace_consume_the_cap(self, workspace_factory, settings):
        """The ceiling is the CLUSTER's, so it counts every in-flight run of this
        source — not just this connection's. A per-connection cap would let ten
        customers each dispatch their ceiling simultaneously."""
        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 3
        other_ws = workspace_factory()
        for i in range(2):
            ScanRun.objects.create(
                workspace=other_ws,
                source=_SOURCE,
                target_ref=f"other-{i}",
                status=ScanRun.Status.RUNNING,
                started_at=timezone.now(),
            )

        conn = _conn(workspace_factory())
        _links(conn, 4)

        with patch(_DISPATCH) as m_dispatch:
            counts = dispatch_connection_scans(conn, trigger="schedule")

        assert m_dispatch.call_count == 1
        assert counts["enqueued"] == 1
        assert counts["deferred"] == 3

    def test_completed_runs_do_not_consume_the_cap(self, workspace_factory, settings):
        """Only PENDING/RUNNING is in flight. Counting finished runs would wedge
        the pillar permanently after the first N scans of its life."""
        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 2
        ws = workspace_factory()
        for i in range(5):
            ScanRun.objects.create(
                workspace=ws,
                source=_SOURCE,
                target_ref=f"done-{i}",
                status=ScanRun.Status.COMPLETED,
                completed_at=timezone.now(),
            )

        conn = _conn(ws)
        _links(conn, 2)

        with patch(_DISPATCH) as m_dispatch:
            counts = dispatch_connection_scans(conn, trigger="schedule")

        assert m_dispatch.call_count == 2
        assert counts["deferred"] == 0

    def test_another_pillars_runs_do_not_consume_this_cap(self, workspace_factory, settings):
        """The cap is per source — a Trivy sweep must not starve CSPM."""
        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 2
        ws = workspace_factory()
        for i in range(4):
            ScanRun.objects.create(
                workspace=ws,
                source="container_security.trivy",
                target_ref=f"img-{i}",
                status=ScanRun.Status.RUNNING,
                started_at=timezone.now(),
            )

        conn = _conn(ws)
        _links(conn, 2)

        with patch(_DISPATCH) as m_dispatch:
            dispatch_connection_scans(conn, trigger="schedule")

        assert m_dispatch.call_count == 2

    def test_a_full_cap_defers_everything_and_dispatches_nothing(self, workspace_factory, settings):
        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 1
        ws = workspace_factory()
        ScanRun.objects.create(
            workspace=ws,
            source=_SOURCE,
            target_ref="busy",
            status=ScanRun.Status.PENDING,
        )

        conn = _conn(ws)
        _links(conn, 3)

        with patch(_DISPATCH) as m_dispatch:
            counts = dispatch_connection_scans(conn, trigger="schedule")

        assert m_dispatch.call_count == 0
        assert counts["scannable"] == 3
        assert counts["enqueued"] == 0
        assert counts["blocked"] == 0
        assert counts["deferred"] == 3
        assert counts["retry_after"] > 0

    def test_a_deferred_account_holds_no_dispatch_lock(self, workspace_factory, settings):
        """Deferral must be free. If the cap took the lock and then declined to
        dispatch, the account would be cooldown-locked for an hour having never
        been scanned — a queue that eats its own work."""
        from django.core.cache import cache

        from components.scanning.infrastructure.services.scan_gate import dispatch_lock_key

        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 1
        ws = workspace_factory()
        conn = _conn(ws)
        _links(conn, 3)

        with patch(_DISPATCH) as m_dispatch:
            dispatch_connection_scans(conn, trigger="schedule")
        dispatched = _dispatched_accounts(m_dispatch)

        deferred = {f"{i:012d}" for i in range(3)} - dispatched
        assert deferred, "nothing was deferred — the cap did not engage, so this asserts nothing"
        for account_id in deferred:
            key = dispatch_lock_key(str(conn.workspace_id), _SOURCE, account_id)
            assert cache.get(key) is None, f"deferred account {account_id} was left holding a lock"

    def test_the_cap_is_off_by_default_config_but_pinned(self, settings):
        """The shipped default is a real number, not None/0 — an unset cap is how
        this regressed in the first place."""
        from django.conf import settings as django_settings

        assert isinstance(django_settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS, int)
        assert django_settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS > 0

    def test_a_nonpositive_cap_means_unbounded_not_frozen(self, workspace_factory, settings):
        """An operator who sets 0 meant "no ceiling", and a typo must never
        silently stop every scan in the fleet."""
        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 0
        conn = _conn(workspace_factory())
        _links(conn, 4)

        with patch(_DISPATCH) as m_dispatch:
            counts = dispatch_connection_scans(conn, trigger="schedule")

        assert m_dispatch.call_count == 4
        assert counts["deferred"] == 0


@pytest.mark.integration
@pytest.mark.django_db
class TestDeferralIsObservable:
    """ "40 scanned, 160 deferred" must be readable by an operator, not inferred."""

    def test_the_beat_sweep_reports_deferrals(self, workspace_factory, settings):
        from django.core.management import call_command

        from components.cloud_posture.infrastructure.tasks.cloud_posture_tasks import (
            schedule_prowler_runs,
        )
        from infrastructure.persistence.core.models import FeatureFlag

        call_command("seed_feature_flags")
        FeatureFlag.objects.update_or_create(key="feature.cloud_posture", defaults={"is_enabled": True})

        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 2
        conn = _conn(workspace_factory())
        _links(conn, 5)

        with patch(_DISPATCH):
            result = schedule_prowler_runs()

        assert result["scheduled"] == 2
        assert result["deferred"] == 3

    def test_the_scan_now_endpoint_reports_deferrals_rather_than_lying(self, api_client, workspace_factory, settings):
        """A 202 saying ``enqueued: 0`` with no other field is indistinguishable
        from success. When the cap swallowed the whole fan-out, say so."""
        from django.core.management import call_command

        from infrastructure.persistence.core.models import FeatureFlag

        call_command("seed_feature_flags")
        FeatureFlag.objects.update_or_create(key="feature.cloud_posture", defaults={"is_enabled": True})

        ws = workspace_factory()
        api_client.force_authenticate(ws.workspace_owner)

        settings.CLOUD_POSTURE_MAX_CONCURRENT_SCANS = 1
        ScanRun.objects.create(workspace=ws, source=_SOURCE, target_ref="busy", status=ScanRun.Status.RUNNING)
        conn = _conn(ws)
        _links(conn, 3)

        with patch(_DISPATCH):
            resp = api_client.post(f"/integrations/workspaces/{ws.id}/aws/{conn.id}/scan/")

        assert resp.status_code == 429, resp.data
        assert resp.data["deferred"] == 3
        assert int(resp["Retry-After"]) > 0
