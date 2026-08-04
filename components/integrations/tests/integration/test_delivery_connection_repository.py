"""Connection resolution + health stamping (ADR 0016 D2).

Covers the behaviour the adapters now rely on: secrets are decrypted here, a row
we cannot authenticate is skipped rather than returned half-formed, and health
lands on the row rather than in the adapter.
"""

from __future__ import annotations

import pytest

from components.integrations.application.providers.secret_envelope_provider import encrypt_secret
from components.integrations.infrastructure.repositories.delivery_connection_repository import (
    DeliveryConnectionRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _make_connection(workspace, **overrides):
    from infrastructure.persistence.integrations.models import DeliveryConnection

    defaults = dict(
        workspace=workspace,
        kind=DeliveryConnection.Kind.SLACK,
        name="Sec alerts",
        auth_mode=DeliveryConnection.AuthMode.BOT_TOKEN,
        config={"channel": "#soc"},
        min_severity="high",
        secret_ciphertext=encrypt_secret("xoxb-token"),
        is_enabled=True,
    )
    defaults.update(overrides)
    return DeliveryConnection.objects.create(**defaults)


class TestEnabledForWorkspace:
    def test_resolves_and_decrypts(self, workspace_factory):
        workspace = workspace_factory()
        _make_connection(workspace)

        resolved = DeliveryConnectionRepository().enabled_for_workspace(workspace.id)

        assert len(resolved) == 1
        assert resolved[0].secret == "xoxb-token"
        assert resolved[0].channel == "#soc"
        assert resolved[0].min_severity == "high"

    def test_min_severity_comes_from_the_column_not_config(self, workspace_factory):
        """The floor was promoted out of ``config`` by migration 0011 — a stale JSON
        copy must never win, or an operator's change would appear to do nothing."""
        workspace = workspace_factory()
        _make_connection(workspace, min_severity="critical", config={"channel": "#soc", "min_severity": "low"})

        resolved = DeliveryConnectionRepository().enabled_for_workspace(workspace.id)

        assert resolved[0].min_severity == "critical"

    def test_disabled_rows_are_excluded(self, workspace_factory):
        workspace = workspace_factory()
        _make_connection(workspace, is_enabled=False)

        assert DeliveryConnectionRepository().enabled_for_workspace(workspace.id) == []

    def test_row_without_a_secret_is_skipped(self, workspace_factory):
        workspace = workspace_factory()
        _make_connection(workspace, secret_ciphertext="")

        assert DeliveryConnectionRepository().enabled_for_workspace(workspace.id) == []

    def test_undecryptable_secret_is_skipped_not_raised(self, workspace_factory):
        """A SECRET_KEY rotation makes stored envelopes unreadable. One unusable
        connection must not break delivery to the others."""
        workspace = workspace_factory()
        _make_connection(workspace, secret_ciphertext="not-a-valid-fernet-token")
        _make_connection(workspace, name="Working")

        resolved = DeliveryConnectionRepository().enabled_for_workspace(workspace.id)

        assert [c.name for c in resolved] == ["Working"]

    def test_filters_by_kind(self, workspace_factory):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        workspace = workspace_factory()
        _make_connection(workspace, kind=DeliveryConnection.Kind.WEBHOOK)

        assert DeliveryConnectionRepository().enabled_for_workspace(workspace.id, kind="slack") == []


class TestHealthStamping:
    def test_mark_delivered_clears_a_previous_error(self, workspace_factory):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        workspace = workspace_factory()
        row = _make_connection(workspace, last_error="channel_not_found", status=DeliveryConnection.Status.ERROR)

        DeliveryConnectionRepository().mark_delivered(row.id)

        row.refresh_from_db()
        assert row.last_error == ""
        assert row.status == DeliveryConnection.Status.CONNECTED
        assert row.last_delivery_at is not None

    def test_mark_error_records_but_does_not_disable(self, workspace_factory):
        """Auto-disable on sustained failure is a deliberate P2 decision — one bad
        response must not silently stop a workspace's alerting."""
        from infrastructure.persistence.integrations.models import DeliveryConnection

        workspace = workspace_factory()
        row = _make_connection(workspace)

        DeliveryConnectionRepository().mark_error(row.id, "invalid_auth")

        row.refresh_from_db()
        assert row.last_error == "invalid_auth"
        assert row.status == DeliveryConnection.Status.ERROR
        assert row.is_enabled is True

    def test_mark_verified_stamps_the_timestamp(self, workspace_factory):
        workspace = workspace_factory()
        row = _make_connection(workspace)

        DeliveryConnectionRepository().mark_verified(row.id, ok=True)

        row.refresh_from_db()
        assert row.last_verified_at is not None
        assert row.last_error == ""
