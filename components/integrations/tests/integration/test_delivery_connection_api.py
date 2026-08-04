"""Delivery-connection CRUD + verify endpoints (ADR 0016 D2).

The load-bearing assertion in here is that the stored credential never leaves the
server — not on create, not on read, not on update, not on verify.
"""

from __future__ import annotations

import pytest

from components.integrations.application.providers.secret_envelope_provider import decrypt_secret

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_WEBHOOK = "https://hooks.slack.com/services/T000/B000/abcdefghijklmnop"


def _url(workspace, suffix: str = "") -> str:
    return f"/integrations/workspaces/{workspace.id}/delivery-connections/{suffix}"


def _create_payload(**overrides) -> dict:
    payload = {
        "kind": "slack",
        "name": "Sec alerts",
        "auth_mode": "webhook_url",
        "secret": _WEBHOOK,
        "min_severity": "high",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def owner_client(api_client, workspace_factory, user_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    api_client.force_authenticate(user=user)
    return api_client, workspace, user


class TestCreate:
    def test_creates_and_never_echoes_the_secret(self, owner_client):
        client, workspace, _ = owner_client

        response = client.post(_url(workspace), _create_payload(), format="json")

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["has_secret"] is True
        assert _WEBHOOK not in response.content.decode()
        assert "secret" not in data

    def test_stores_the_secret_encrypted(self, owner_client):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        client, workspace, _ = owner_client
        client.post(_url(workspace), _create_payload(), format="json")

        row = DeliveryConnection.objects.get(workspace=workspace)
        assert row.secret_ciphertext != _WEBHOOK, "the credential must never be stored in plaintext"
        assert decrypt_secret(row.secret_ciphertext) == _WEBHOOK

    def test_records_the_creator(self, owner_client):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        client, workspace, user = owner_client
        client.post(_url(workspace), _create_payload(), format="json")

        assert DeliveryConnection.objects.get(workspace=workspace).created_by_id == user.id

    def test_rejects_an_invalid_webhook_url(self, owner_client):
        client, workspace, _ = owner_client

        response = client.post(
            _url(workspace), _create_payload(secret="https://evil.test/services/a/b/c"), format="json"
        )

        assert response.status_code == 400
        assert "hooks.slack.com" in response.json()["error"]

    def test_rejects_a_kind_with_no_adapter(self, owner_client):
        client, workspace, _ = owner_client

        response = client.post(_url(workspace), _create_payload(kind="webhook"), format="json")

        assert response.status_code == 400


class TestList:
    def test_lists_only_this_workspace(self, owner_client, workspace_factory):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        client, workspace, _ = owner_client
        other = workspace_factory()
        DeliveryConnection.objects.create(
            workspace=other, kind="slack", name="Someone else", secret_ciphertext="x"
        )
        client.post(_url(workspace), _create_payload(), format="json")

        response = client.get(_url(workspace))

        assert response.status_code == 200
        names = [row["name"] for row in response.json()["data"]]
        assert names == ["Sec alerts"], "tenancy leak — another workspace's connection was listed"

    def test_never_returns_the_secret(self, owner_client):
        client, workspace, _ = owner_client
        client.post(_url(workspace), _create_payload(), format="json")

        response = client.get(_url(workspace))

        assert _WEBHOOK not in response.content.decode()


class TestUpdate:
    def test_renaming_leaves_the_credential_intact(self, owner_client):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        client, workspace, _ = owner_client
        created = client.post(_url(workspace), _create_payload(), format="json").json()["data"]

        response = client.patch(_url(workspace, f"{created['id']}/"), {"name": "Renamed"}, format="json")

        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Renamed"
        row = DeliveryConnection.objects.get(id=created["id"])
        assert decrypt_secret(row.secret_ciphertext) == _WEBHOOK, "editing a label must not wipe auth"

    def test_rotating_the_secret_clears_the_previous_verification(self, owner_client):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        client, workspace, _ = owner_client
        created = client.post(_url(workspace), _create_payload(), format="json").json()["data"]
        DeliveryConnection.objects.filter(id=created["id"]).update(last_verified_at="2026-01-01T00:00:00Z")

        new_url = "https://hooks.slack.com/services/T111/B111/zzzzzzzzzzzzzzzz"
        response = client.patch(_url(workspace, f"{created['id']}/"), {"secret": new_url}, format="json")

        assert response.status_code == 200
        assert response.json()["data"]["last_verified_at"] is None, "a rotated credential is unverified"
        row = DeliveryConnection.objects.get(id=created["id"])
        assert decrypt_secret(row.secret_ciphertext) == new_url

    def test_cannot_reach_another_workspaces_connection(self, owner_client, workspace_factory):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        client, workspace, _ = owner_client
        foreign = DeliveryConnection.objects.create(
            workspace=workspace_factory(), kind="slack", name="Theirs", secret_ciphertext="x"
        )

        response = client.patch(_url(workspace, f"{foreign.id}/"), {"name": "Hijacked"}, format="json")

        assert response.status_code == 404


class TestDelete:
    def test_deletes(self, owner_client):
        from infrastructure.persistence.integrations.models import DeliveryConnection

        client, workspace, _ = owner_client
        created = client.post(_url(workspace), _create_payload(), format="json").json()["data"]

        response = client.delete(_url(workspace, f"{created['id']}/"))

        assert response.status_code == 200
        assert not DeliveryConnection.objects.filter(id=created["id"]).exists()


class TestVerify:
    def test_success_stamps_verified(self, owner_client, monkeypatch):
        from components.integrations.infrastructure.adapters import slack_delivery_adapter as mod

        class _Resp:
            status_code = 200
            content = b"ok"
            headers: dict = {}

            def json(self):
                raise ValueError("no json")

        monkeypatch.setattr(mod.requests, "post", lambda url, **kw: _Resp())

        client, workspace, _ = owner_client
        created = client.post(_url(workspace), _create_payload(), format="json").json()["data"]

        response = client.post(_url(workspace, f"{created['id']}/verify/"), format="json")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "connected"
        assert data["last_verified_at"] is not None
        assert data["last_error"] == ""

    def test_failure_is_200_with_the_reason_on_the_row(self, owner_client, monkeypatch):
        """The panel reads data.status/last_error — a 502 would break that contract
        and hide the reason the operator needs."""
        from components.integrations.infrastructure.adapters import slack_delivery_adapter as mod

        class _Resp:
            status_code = 404
            content = b"no_service"
            headers: dict = {}

            def json(self):
                raise ValueError("no json")

        monkeypatch.setattr(mod.requests, "post", lambda url, **kw: _Resp())

        client, workspace, _ = owner_client
        created = client.post(_url(workspace), _create_payload(), format="json").json()["data"]

        response = client.post(_url(workspace, f"{created['id']}/verify/"), format="json")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "error"
        assert data["last_error"]
        assert _WEBHOOK not in response.content.decode()
