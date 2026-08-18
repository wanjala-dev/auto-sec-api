"""Integration: the post-merge verification rescan task (#118).

``code_security.rescan_repo_after_remediation`` is dispatched BY NAME by the
remediation reconciler when a draft PR is confirmed merged. Pins the task's
gates in order: the feature flag self-gate, the consent (allowlist) gate that is
NEVER bypassed, the cooldown exemption (the whole point — a fix verifies closed
now, not after the anti-spam window), the ``merge_rescan`` provenance stamp, and
the bounded retry when a possibly-pre-merge scan is already in flight.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry
from django.core.cache import cache
from django.utils import timezone

from components.code_security.infrastructure.tasks.code_security_tasks import (
    rescan_repo_after_remediation,
)
from components.scanning.application.providers import scan_dispatch_provider
from infrastructure.persistence.integrations.models import VcsConnection
from infrastructure.persistence.scanning.models import ScanRun

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_SOURCE = "code_security.opengrep"
_REPO = "acme/app"
_FLAGS_PROVIDER = "components.shared_platform.application.providers.feature_flags_provider.get_feature_flags_provider"


class _FakeAsyncResult:
    id = "scan-task-1"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture()
def _dispatch_spy(monkeypatch):
    calls = []

    def _fake_dispatch(**kwargs):
        calls.append(kwargs)
        return _FakeAsyncResult()

    monkeypatch.setattr(scan_dispatch_provider, "dispatch_scan", _fake_dispatch)
    return calls


@pytest.fixture()
def _flag_on():
    flags = MagicMock()
    flags.is_feature_enabled.return_value = True
    with patch(_FLAGS_PROVIDER, return_value=flags):
        yield flags


def _connection(ws, *, allowlist=(_REPO,)):
    return VcsConnection.objects.create(
        workspace=ws,
        provider=VcsConnection.Provider.GITHUB,
        name="GitHub",
        repo_allowlist=list(allowlist),
        status=VcsConnection.Status.CONNECTED,
    )


def test_rescan_bypasses_an_active_cooldown_and_stamps_merge_provenance(workspace_factory, _dispatch_spy, _flag_on):
    """The core of #118: the repo completed a scan 10 minutes ago (cooldown active
    for every other trigger), yet the merge-triggered rescan dispatches — with
    ``trigger="merge_rescan"`` provenance on the run."""
    ws = workspace_factory()
    _connection(ws)
    ScanRun.objects.create(
        workspace=ws,
        source=_SOURCE,
        target_ref=_REPO,
        status=ScanRun.Status.COMPLETED,
        started_at=timezone.now() - timedelta(minutes=11),
        completed_at=timezone.now() - timedelta(minutes=10),
    )

    result = rescan_repo_after_remediation(str(ws.id), _REPO)

    assert result == {"dispatched": True, "scan_task_id": "scan-task-1"}
    assert len(_dispatch_spy) == 1
    assert _dispatch_spy[0]["trigger"] == "merge_rescan"
    assert _dispatch_spy[0]["target_ref"] == _REPO
    assert _dispatch_spy[0]["triggered_by"] is None  # system-triggered, no operator


def test_flag_off_skips_without_dispatching(workspace_factory, _dispatch_spy):
    ws = workspace_factory()
    _connection(ws)
    flags = MagicMock()
    flags.is_feature_enabled.return_value = False

    with patch(_FLAGS_PROVIDER, return_value=flags):
        result = rescan_repo_after_remediation(str(ws.id), _REPO)

    assert result == {"dispatched": False, "reason": "flag_off"}
    assert _dispatch_spy == []


def test_consent_gate_is_never_bypassed(workspace_factory, _dispatch_spy, _flag_on):
    """A repo removed from the allowlist since the PR opened must NOT be scanned —
    the cooldown exemption never widens consent. Graceful (no raise): the nightly
    beat remains the safety net if consent returns."""
    ws = workspace_factory()
    _connection(ws, allowlist=("other/repo",))

    result = rescan_repo_after_remediation(str(ws.id), _REPO)

    assert result == {"dispatched": False, "reason": "repo_not_allowlisted"}
    assert _dispatch_spy == []


def test_in_flight_scan_triggers_a_bounded_retry(workspace_factory, _dispatch_spy, _flag_on):
    """A scan already running may have checked the tree out BEFORE the merge —
    the task retries (countdown) instead of trusting a possibly-stale scan."""
    ws = workspace_factory()
    _connection(ws)
    ScanRun.objects.create(
        workspace=ws,
        source=_SOURCE,
        target_ref=_REPO,
        status=ScanRun.Status.RUNNING,
        started_at=timezone.now(),
    )

    with pytest.raises(Retry):
        rescan_repo_after_remediation.apply(args=(str(ws.id), _REPO), throw=True).get()

    assert _dispatch_spy == []
