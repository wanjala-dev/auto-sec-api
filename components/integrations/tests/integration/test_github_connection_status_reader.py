"""Integration tests — the GitHub credential-status read port (SECRET HAZARD).

``GitHubConnection`` stores an encrypted PAT in ``token_ciphertext``. The
AI-governance credential inventory reads this connection's surface through
``GitHubConnectionStatusReadPort`` — and the whole point of that seam is that the
ciphertext is reduced to a presence boolean INSIDE the adapter and NEVER crosses
the port boundary. These tests prove exactly that:

* the returned DTO exposes ``has_token`` but carries no token / ciphertext field;
* the encrypted token string never appears anywhere in the returned data;
* presence is reported honestly (True when a ciphertext exists, False when blank);
* the read is workspace-scoped (a connection in another workspace never leaks).
"""

from __future__ import annotations

import dataclasses

import pytest

from components.integrations.application.ports.github_connection_status_port import (
    GitHubConnectionStatus,
)
from components.integrations.application.providers.github_connection_status_provider import (
    get_github_connection_status_reader,
)
from infrastructure.persistence.integrations.models import GitHubConnection

_SECRET_CIPHERTEXT = "gAAAAAB-super-secret-ciphertext-should-never-leak"


@pytest.fixture()
def reader():
    return get_github_connection_status_reader()


@pytest.mark.django_db
class TestGitHubConnectionStatusReader:
    def test_dto_has_no_token_field_at_all(self):
        # The DTO schema itself must never carry a token/ciphertext field.
        field_names = {f.name for f in dataclasses.fields(GitHubConnectionStatus)}
        assert "has_token" in field_names
        for forbidden in ("token", "token_ciphertext", "ciphertext", "secret", "pat"):
            assert forbidden not in field_names, f"DTO leaks a secret field: {forbidden}"

    def test_ciphertext_never_crosses_the_port(self, reader, workspace_factory):
        ws = workspace_factory()
        GitHubConnection.objects.create(
            workspace=ws,
            name="GitHub",
            repo_allowlist=["acme/app"],
            token_ciphertext=_SECRET_CIPHERTEXT,
            status=GitHubConnection.Status.CONNECTED,
        )

        statuses = reader.list_statuses(workspace_id=str(ws.id))

        assert len(statuses) == 1
        status = statuses[0]
        # Presence reported, token itself absent.
        assert status.has_token is True
        # The ciphertext must not appear ANYWHERE in the returned DTO.
        blob = repr(dataclasses.asdict(status))
        assert _SECRET_CIPHERTEXT not in blob
        assert "token" not in dataclasses.asdict(status)
        # Non-secret facts still surface for the inventory.
        assert status.name == "GitHub"
        assert status.status == GitHubConnection.Status.CONNECTED
        assert status.repo_allowlist == ["acme/app"]

    def test_absent_token_reports_has_token_false(self, reader, workspace_factory):
        ws = workspace_factory()
        GitHubConnection.objects.create(
            workspace=ws,
            name="GitHub",
            repo_allowlist=[],
            token_ciphertext="",
            status=GitHubConnection.Status.DISABLED,
        )

        statuses = reader.list_statuses(workspace_id=str(ws.id))

        assert len(statuses) == 1
        assert statuses[0].has_token is False

    def test_read_is_workspace_scoped(self, reader, workspace_factory):
        ws_a = workspace_factory()
        ws_b = workspace_factory()
        GitHubConnection.objects.create(
            workspace=ws_b,
            name="Other-WS GitHub",
            token_ciphertext=_SECRET_CIPHERTEXT,
            status=GitHubConnection.Status.CONNECTED,
        )

        statuses = reader.list_statuses(workspace_id=str(ws_a.id))

        # ws_a has no connections — ws_b's secret-bearing row never leaks.
        assert statuses == []
