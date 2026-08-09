"""The Vercel trigger gate (ADR 0021 D3) — the audit-mandated proof it actually engages.

The scanner-architecture audit found the gate's cooldown layer reads ``ScanRun``
history ONLY — a pillar that never writes runs gets a gate that silently never
engages. Vercel rides the spine precisely so this works: these tests exercise the
REAL ``check_and_lock_dispatch`` (ScanRun history + atomic cache lock) through the
trigger use case, with only the Celery dispatch stubbed.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.utils import timezone

from components.cloud_posture.application.use_cases.trigger_vercel_scan_use_case import (
    SOURCE,
    TriggerVercelScanUseCase,
    VercelScanRejected,
)
from infrastructure.persistence.scanning.models import ScanRun

_TEAM = "team_gate1234"
_DISPATCH = "components.scanning.infrastructure.tasks.scan_tasks.dispatch_scan"


@pytest.fixture(autouse=True)
def _clean_gate_cache():
    cache.clear()
    yield
    cache.clear()


def _execute(workspace, connection_id="11111111-1111-1111-1111-111111111111", **kwargs):
    return TriggerVercelScanUseCase().execute(
        workspace_id=workspace.id, connection_id=connection_id, team=_TEAM, **kwargs
    )


@pytest.mark.integration
@pytest.mark.django_db
class TestVercelScanGate:
    def test_dispatches_with_provider_param_and_provenance(self, workspace_factory):
        ws = workspace_factory()
        with mock.patch(_DISPATCH) as dispatch:
            dispatch.return_value = mock.Mock(id="task-1")
            result = _execute(ws, trigger="manual", triggered_by="99999999-9999-9999-9999-999999999999")

        assert result["source"] == SOURCE
        kwargs = dispatch.call_args.kwargs
        assert kwargs["source"] == "cloud_posture.prowler.vercel"
        assert kwargs["target_ref"] == _TEAM
        assert kwargs["params"] == {"provider": "vercel"}
        assert kwargs["trigger"] == "manual"
        assert kwargs["triggered_by"] == "99999999-9999-9999-9999-999999999999"

    def test_second_dispatch_is_blocked_while_the_first_is_queued(self, workspace_factory):
        # The atomic cache lock covers the queued-but-not-yet-started window.
        ws = workspace_factory()
        with mock.patch(_DISPATCH) as dispatch:
            dispatch.return_value = mock.Mock(id="task-1")
            _execute(ws)
            with pytest.raises(VercelScanRejected) as excinfo:
                _execute(ws)
        assert excinfo.value.code == "scan_already_running"

    def test_completed_run_starts_the_cooldown(self, workspace_factory):
        ws = workspace_factory()
        ScanRun.objects.create(
            workspace=ws,
            source=SOURCE,
            target_ref=_TEAM,
            status=ScanRun.Status.COMPLETED,
            completed_at=timezone.now() - timedelta(minutes=5),
        )
        with mock.patch(_DISPATCH), pytest.raises(VercelScanRejected) as excinfo:
            _execute(ws)
        assert excinfo.value.code == "scan_cooldown"
        assert excinfo.value.retry_after is not None and excinfo.value.retry_after > 0

    def test_failed_run_does_not_start_a_cooldown(self, workspace_factory):
        # A transient engine failure must not lock the team for an hour.
        ws = workspace_factory()
        ScanRun.objects.create(
            workspace=ws,
            source=SOURCE,
            target_ref=_TEAM,
            status=ScanRun.Status.FAILED,
            completed_at=timezone.now() - timedelta(minutes=5),
        )
        with mock.patch(_DISPATCH) as dispatch:
            dispatch.return_value = mock.Mock(id="task-2")
            result = _execute(ws)
        assert result["team"] == _TEAM

    def test_enqueue_failure_releases_the_lock(self, workspace_factory):
        # If the broker enqueue itself blows up, the lock must not stay stuck.
        ws = workspace_factory()
        with mock.patch(_DISPATCH, side_effect=RuntimeError("broker down")), pytest.raises(RuntimeError):
            _execute(ws)
        # The lock was released → an immediate retry is allowed.
        with mock.patch(_DISPATCH) as dispatch:
            dispatch.return_value = mock.Mock(id="task-3")
            result = _execute(ws)
        assert result["team"] == _TEAM

    def test_malformed_team_is_rejected_before_any_lock(self, workspace_factory):
        ws = workspace_factory()
        with pytest.raises(VercelScanRejected) as excinfo:
            TriggerVercelScanUseCase().execute(workspace_id=ws.id, connection_id="x", team="acme;rm -rf /")
        assert excinfo.value.code == "invalid_team"
