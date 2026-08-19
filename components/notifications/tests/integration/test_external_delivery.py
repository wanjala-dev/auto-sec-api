"""The external leg end to end (ADR 0016 D5/D7).

Two properties carry the feature and both are exercised here:

* **Idempotency** — a redelivered task must not double-post to a customer's channel.
* **Truthful skips** — every non-send records *why*, so an operator can always answer
  "so why didn't this reach Slack?" without reading code.
"""

from __future__ import annotations

import pytest

from components.integrations.application.providers.secret_envelope_provider import encrypt_secret
from components.notifications.infrastructure.repositories.external_delivery_repository import (
    ExternalDeliveryRepository,
)
from components.notifications.infrastructure.tasks import external_delivery_tasks as mod
from components.shared_kernel.domain.delivery_events import DRAFT_PR_OPENED, FINDING_CRITICAL

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_WEBHOOK = "https://hooks.slack.com/services/T0/B0/abcdefghijklmnop"


def _connection(workspace, **overrides):
    from infrastructure.persistence.integrations.models import DeliveryConnection

    defaults = dict(
        workspace=workspace,
        kind=DeliveryConnection.Kind.SLACK,
        name="Sec alerts",
        auth_mode=DeliveryConnection.AuthMode.WEBHOOK_URL,
        secret_ciphertext=encrypt_secret(_WEBHOOK),
        min_severity="high",
        events=[FINDING_CRITICAL, DRAFT_PR_OPENED],
        is_enabled=True,
    )
    defaults.update(overrides)
    return DeliveryConnection.objects.create(**defaults)


class _Recorder:
    """Stands in for the Slack adapter so nothing leaves the test."""

    def __init__(self, result=None):
        from components.integrations.application.ports.delivery_channel_port import DeliveryResult

        self.result = result or DeliveryResult(ok=True)
        self.calls: list = []

    def deliver(self, connection, message):
        self.calls.append((connection, message))
        return self.result

    def verify(self, connection):  # pragma: no cover
        raise NotImplementedError


def _run(monkeypatch, workspace, *, adapter, event_key=FINDING_CRITICAL, metadata=None):
    class _Provider:
        def get(self, kind):
            return adapter

    # The task imports the provider INSIDE its body, so the name resolves from the
    # source module at call time — patching the task module would silently do
    # nothing. No ``raising=False``: a wrong target should fail loudly rather than
    # leave the test asserting against the real Slack adapter.
    import components.integrations.application.providers.delivery_channel_provider as provider_mod

    monkeypatch.setattr(provider_mod, "get_delivery_channel_provider", lambda: _Provider())
    return mod.deliver_external.apply(
        kwargs={
            "workspace_id": str(workspace.id),
            "event_key": event_key,
            "verb": "Public S3 bucket",
            "metadata": metadata if metadata is not None else {"severity": "critical", "finding_id": "f-1"},
            "link": "https://app.example.com/findings/1",
        }
    ).get()


class TestDelivery:
    def test_delivers_to_a_subscribed_connection(self, workspace_factory, monkeypatch):
        workspace = workspace_factory()
        connection = _connection(workspace)
        adapter = _Recorder()

        result = _run(monkeypatch, workspace, adapter=adapter)

        assert result["delivered"] == 1
        assert len(adapter.calls) == 1
        # The success path stamps connection health — the Settings panel's
        # "last delivery" proof that alerts actually reach the channel.
        connection.refresh_from_db()
        assert connection.last_delivery_at is not None

    def test_skipped_delivery_does_not_stamp_last_delivery(self, workspace_factory, monkeypatch):
        workspace = workspace_factory()
        connection = _connection(workspace, events=[DRAFT_PR_OPENED])  # not subscribed
        adapter = _Recorder()

        result = _run(monkeypatch, workspace, adapter=adapter)

        assert result["delivered"] == 0
        connection.refresh_from_db()
        assert connection.last_delivery_at is None

    def test_redelivery_does_not_double_post(self, workspace_factory, monkeypatch):
        """The whole point of the ledger — a retried task converges instead of
        posting a second message to a customer's channel."""
        workspace = workspace_factory()
        _connection(workspace)
        adapter = _Recorder()

        first = _run(monkeypatch, workspace, adapter=adapter)
        second = _run(monkeypatch, workspace, adapter=adapter)

        assert first["delivered"] == 1
        assert second["delivered"] == 0
        assert len(adapter.calls) == 1, "the same event was posted twice"

    def test_no_connections_is_a_noop(self, workspace_factory, monkeypatch):
        workspace = workspace_factory()
        adapter = _Recorder()

        result = _run(monkeypatch, workspace, adapter=adapter)

        assert result == {"delivered": 0, "skipped": 0, "connections": 0}
        assert adapter.calls == []


class TestGates:
    def _skip_reason(self, workspace):
        from infrastructure.persistence.notifications.models import ExternalDelivery

        row = ExternalDelivery.objects.filter(connection__workspace=workspace).first()
        return (row.status, row.last_error) if row else (None, None)

    def test_unsubscribed_event_is_skipped_with_a_reason(self, workspace_factory, monkeypatch):
        workspace = workspace_factory()
        _connection(workspace, events=[DRAFT_PR_OPENED])  # not subscribed to findings
        adapter = _Recorder()

        result = _run(monkeypatch, workspace, adapter=adapter)

        assert result["delivered"] == 0
        assert adapter.calls == []
        status, reason = self._skip_reason(workspace)
        assert status == "skipped"
        assert reason == mod.NOT_SUBSCRIBED_REASON

    def test_below_severity_floor_is_skipped(self, workspace_factory, monkeypatch):
        workspace = workspace_factory()
        _connection(workspace, min_severity="critical")
        adapter = _Recorder()

        result = _run(monkeypatch, workspace, adapter=adapter, metadata={"severity": "high", "finding_id": "f-1"})

        assert result["delivered"] == 0
        status, reason = self._skip_reason(workspace)
        assert reason == mod.BELOW_FLOOR_REASON

    def test_kev_bypasses_the_severity_floor(self, workspace_factory, monkeypatch):
        """A known-exploited vulnerability is never noise, whatever the dial says."""
        workspace = workspace_factory()
        _connection(workspace, min_severity="critical")
        adapter = _Recorder()

        result = _run(
            monkeypatch,
            workspace,
            adapter=adapter,
            metadata={"severity": "high", "finding_id": "f-1", "in_kev": True},
        )

        assert result["delivered"] == 1

    def test_re_observation_is_skipped(self, workspace_factory, monkeypatch):
        workspace = workspace_factory()
        _connection(workspace)
        adapter = _Recorder()

        result = _run(
            monkeypatch,
            workspace,
            adapter=adapter,
            metadata={"severity": "critical", "finding_id": "f-1", "is_new": False},
        )

        assert result["delivered"] == 0
        _, reason = self._skip_reason(workspace)
        assert reason == mod.RE_OBSERVATION_REASON

    def test_disabled_connection_is_not_even_resolved(self, workspace_factory, monkeypatch):
        workspace = workspace_factory()
        _connection(workspace, is_enabled=False)
        adapter = _Recorder()

        result = _run(monkeypatch, workspace, adapter=adapter)

        assert result["connections"] == 0

    def test_channel_flag_off_is_a_truthful_skip(self, workspace_factory, monkeypatch, settings):
        """A flag-off environment records why — the ledger never claims a send
        that didn't happen."""
        settings.NOTIF_EXTERNAL_CHANNEL_ENABLED = False
        workspace = workspace_factory()
        _connection(workspace)
        adapter = _Recorder()

        result = _run(monkeypatch, workspace, adapter=adapter)

        assert result["delivered"] == 0
        assert adapter.calls == []
        _, reason = self._skip_reason(workspace)
        assert reason == mod.CHANNEL_DISABLED_REASON


class TestFailureHandling:
    def test_permanent_failure_is_recorded_and_not_retried(self, workspace_factory, monkeypatch):
        from components.integrations.application.ports.delivery_channel_port import DeliveryResult

        workspace = workspace_factory()
        _connection(workspace)
        adapter = _Recorder(DeliveryResult(ok=False, detail="no_service", permanent=True))

        result = _run(monkeypatch, workspace, adapter=adapter)

        assert result["delivered"] == 0
        from infrastructure.persistence.notifications.models import ExternalDelivery

        row = ExternalDelivery.objects.get(connection__workspace=workspace)
        assert row.status == "failed"
        assert row.last_error == "no_service"

    def test_transient_failure_leaves_the_row_re_claimable(self, workspace_factory, monkeypatch):
        """A failed row must stay claimable or a Celery retry would silently drop
        a live alert — the subtle failure mode the unique constraint introduces."""
        from components.integrations.application.ports.delivery_channel_port import DeliveryResult

        workspace = workspace_factory()
        connection = _connection(workspace)
        adapter = _Recorder(DeliveryResult(ok=False, detail="upstream 503"))

        with pytest.raises(Exception):
            _run(monkeypatch, workspace, adapter=adapter)

        from infrastructure.persistence.notifications.models import ExternalDelivery

        row = ExternalDelivery.objects.get(connection=connection)
        assert row.status == "failed"
        assert ExternalDeliveryRepository().claim(row.id) is True, "a retry must be able to re-claim"


class TestConnectionHealthOnFailure:
    """A failed delivery must show up on the connection, not only in the ledger.

    The ledger has no controller, serializer, or UI — the Settings panel renders the
    connection row. If a failure never lands there, a revoked webhook keeps reporting
    CONNECTED while every alert to it is dropped: the silent-success failure this
    product exists to prevent.
    """

    def test_permanent_failure_marks_the_connection(self, workspace_factory, monkeypatch):
        from components.integrations.application.ports.delivery_channel_port import DeliveryResult

        workspace = workspace_factory()
        connection = _connection(workspace)
        adapter = _Recorder(DeliveryResult(ok=False, detail="invalid_auth", permanent=True))

        _run(monkeypatch, workspace, adapter=adapter)

        connection.refresh_from_db()
        assert connection.status == "error"
        assert connection.last_error == "invalid_auth"

    def test_transient_failure_marks_the_connection(self, workspace_factory, monkeypatch):
        """A retryable failure is still a failure the operator can see right now —
        the panel must not claim CONNECTED while the task backs off."""
        from celery.exceptions import Retry

        from components.integrations.application.ports.delivery_channel_port import DeliveryResult

        workspace = workspace_factory()
        connection = _connection(workspace)
        adapter = _Recorder(DeliveryResult(ok=False, detail="upstream 503"))

        # Named, not a blind ``Exception``: the point of this case is that the task
        # asked Celery to retry, and a bare catch-all would pass just as happily on
        # an unrelated crash.
        with pytest.raises(Retry):
            _run(monkeypatch, workspace, adapter=adapter)

        connection.refresh_from_db()
        assert connection.status == "error"
        assert connection.last_error == "upstream 503"

    def test_a_later_success_clears_the_error(self, workspace_factory, monkeypatch):
        """Health must be the LAST attempt's outcome, never a sticky tombstone —
        a re-pointed webhook has to be able to go green again on its own."""
        from components.integrations.application.ports.delivery_channel_port import DeliveryResult

        workspace = workspace_factory()
        connection = _connection(workspace)

        _run(
            monkeypatch,
            workspace,
            adapter=_Recorder(DeliveryResult(ok=False, detail="invalid_auth", permanent=True)),
            metadata={"severity": "critical", "finding_id": "f-fail"},
        )
        connection.refresh_from_db()
        assert connection.status == "error"

        _run(
            monkeypatch,
            workspace,
            adapter=_Recorder(),
            metadata={"severity": "critical", "finding_id": "f-ok"},
        )

        connection.refresh_from_db()
        assert connection.status == "connected"
        assert connection.last_error == ""

    def test_a_skipped_delivery_does_not_mark_the_connection(self, workspace_factory, monkeypatch):
        """A gate is not a fault — an unsubscribed event must never paint the row red."""
        workspace = workspace_factory()
        connection = _connection(workspace, events=[DRAFT_PR_OPENED])
        adapter = _Recorder()

        _run(monkeypatch, workspace, adapter=adapter)

        connection.refresh_from_db()
        assert connection.status == "connected"
        assert connection.last_error == ""


class TestLedgerClaim:
    def test_only_one_caller_wins_a_claim(self, workspace_factory):
        """The conditional UPDATE is what stops two workers both posting."""
        workspace = workspace_factory()
        connection = _connection(workspace)
        ledger = ExternalDeliveryRepository()

        record = ledger.record(connection_id=connection.id, dedup_key="k1", event_key=FINDING_CRITICAL)

        assert ledger.claim(record.id) is True
        assert ledger.claim(record.id) is False, "a second worker must lose the race"

    def test_a_sent_row_can_never_be_re_claimed(self, workspace_factory):
        workspace = workspace_factory()
        connection = _connection(workspace)
        ledger = ExternalDeliveryRepository()

        record = ledger.record(connection_id=connection.id, dedup_key="k1", event_key=FINDING_CRITICAL)
        ledger.claim(record.id)
        ledger.mark_sent(record.id)

        assert ledger.claim(record.id) is False

    def test_record_is_idempotent(self, workspace_factory):
        workspace = workspace_factory()
        connection = _connection(workspace)
        ledger = ExternalDeliveryRepository()

        first = ledger.record(connection_id=connection.id, dedup_key="k1", event_key=FINDING_CRITICAL)
        second = ledger.record(connection_id=connection.id, dedup_key="k1", event_key=FINDING_CRITICAL)

        assert first.created is True
        assert second.created is False
        assert first.id == second.id
