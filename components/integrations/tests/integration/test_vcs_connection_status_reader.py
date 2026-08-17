"""Integration tests — the VCS credential-status read port (SECRET HAZARD).

``VcsConnection`` stores an encrypted PAT in ``token_ciphertext`` (PAT mode) or a
bound App installation id (app mode — no stored secret). The AI-governance
credential inventory reads this surface through ``VcsConnectionStatusReadPort`` —
and the whole point of that seam is that the ciphertext is reduced to a presence
boolean INSIDE the adapter and NEVER crosses the port boundary. These tests prove:

* a PAT-mode connection is inventoried (the Phase-A surface, unchanged);
* an app-mode connection is inventoried too — the governance gap this reader
  migration closes (the old reader read only the deprecated ``GitHubConnection``
  model, so an installed GitHub App was INVISIBLE to the credential inventory);
* the returned DTO exposes ``has_token`` but carries no token / ciphertext field,
  and no token-cache material ever appears in the returned data;
* a revoked-on-GitHub connection reads honestly (status ``disabled`` + the
  revocation note in ``last_error``);
* the deprecated ``GitHubConnection`` model is NOT double-counted (migration 0008
  copied its rows into ``VcsConnection`` preserving ids — the reader reads only
  ``VcsConnection``);
* the read is workspace-scoped (a connection in another workspace never leaks).
"""

from __future__ import annotations

import dataclasses

import pytest

from components.integrations.application.ports.vcs_connection_status_port import (
    VcsConnectionStatus,
)
from components.integrations.application.providers.vcs_connection_status_provider import (
    get_vcs_connection_status_reader,
)
from infrastructure.persistence.integrations.models import GitHubConnection, VcsConnection

_SECRET_CIPHERTEXT = "gAAAAAB-super-secret-ciphertext-should-never-leak"


@pytest.fixture()
def reader():
    return get_vcs_connection_status_reader()


@pytest.mark.django_db
class TestVcsConnectionStatusReader:
    def test_dto_has_no_token_field_at_all(self):
        # The DTO schema itself must never carry a token/ciphertext field.
        field_names = {f.name for f in dataclasses.fields(VcsConnectionStatus)}
        assert "has_token" in field_names
        for forbidden in ("token", "token_ciphertext", "ciphertext", "secret", "pat"):
            assert forbidden not in field_names, f"DTO leaks a secret field: {forbidden}"

    def test_pat_mode_connection_is_inventoried_without_secrets(self, reader, workspace_factory):
        ws = workspace_factory()
        VcsConnection.objects.create(
            workspace=ws,
            provider=VcsConnection.Provider.GITHUB,
            name="GitHub",
            auth_mode=VcsConnection.AuthMode.PAT,
            repo_allowlist=["acme/app"],
            token_ciphertext=_SECRET_CIPHERTEXT,
            status=VcsConnection.Status.CONNECTED,
        )

        statuses = reader.list_statuses(workspace_id=str(ws.id))

        assert len(statuses) == 1
        status = statuses[0]
        assert status.provider == "github"
        assert status.auth_mode == "pat"
        assert status.installation_id is None
        assert status.has_token is True
        assert status.credential == "fine-grained PAT (encrypted)"
        assert status.repo_allowlist == ["acme/app"]
        # The ciphertext must not appear ANYWHERE in the returned DTO.
        blob = repr(dataclasses.asdict(status))
        assert _SECRET_CIPHERTEXT not in blob

    def test_app_mode_connection_is_inventoried(self, reader, workspace_factory):
        """The gap this migration closes: an installed GitHub App is a live,
        AI-reachable credential — governance must see it (the old reader read only
        the deprecated ``GitHubConnection`` model, so it reported nothing)."""
        ws = workspace_factory()
        VcsConnection.objects.create(
            workspace=ws,
            provider=VcsConnection.Provider.GITHUB,
            name="GitHub App",
            auth_mode=VcsConnection.AuthMode.GITHUB_APP,
            installation_id=4242,
            repo_allowlist=["acme/app", "acme/infra"],
            token_ciphertext="",  # app mode stores NO secret on the row
            status=VcsConnection.Status.CONNECTED,
        )

        statuses = reader.list_statuses(workspace_id=str(ws.id))

        assert len(statuses) == 1
        status = statuses[0]
        assert status.auth_mode == "github_app"
        assert status.installation_id == 4242
        # An app installation IS a usable credential — mints tokens on demand.
        assert status.has_token is True
        assert status.credential == "GitHub App installation 4242"
        assert status.repo_allowlist == ["acme/app", "acme/infra"]

    def test_app_mode_never_surfaces_token_cache_material(self, reader, workspace_factory):
        """Installation tokens live in the Django cache, not on the row — assert the
        DTO carries only the (non-secret) installation id, never a token shape."""
        from django.core.cache import cache

        ws = workspace_factory()
        VcsConnection.objects.create(
            workspace=ws,
            auth_mode=VcsConnection.AuthMode.GITHUB_APP,
            installation_id=555,
            status=VcsConnection.Status.CONNECTED,
        )
        cached_token = "ghs_cached-installation-token-never-leaks"
        cache.set("integrations:github_app:installation_token:v1::555", cached_token, 60)
        try:
            statuses = reader.list_statuses(workspace_id=str(ws.id))
            blob = repr([dataclasses.asdict(s) for s in statuses])
            assert cached_token not in blob
            assert "ghs_" not in blob
        finally:
            cache.delete("integrations:github_app:installation_token:v1::555")

    def test_pat_mode_without_token_reports_no_usable_credential(self, reader, workspace_factory):
        ws = workspace_factory()
        VcsConnection.objects.create(
            workspace=ws,
            auth_mode=VcsConnection.AuthMode.PAT,
            token_ciphertext="",
            status=VcsConnection.Status.DISABLED,
        )

        statuses = reader.list_statuses(workspace_id=str(ws.id))

        assert len(statuses) == 1
        assert statuses[0].has_token is False
        assert statuses[0].credential == "none (no stored credential)"

    def test_revoked_on_github_reads_as_disabled_with_the_revocation_note(self, reader, workspace_factory):
        """The revocation-sync task disables the row and names why — the inventory
        must represent that honestly, not as a healthy credential."""
        ws = workspace_factory()
        note = "GitHub App installation 4242 was deleted on GitHub — connection deactivated (revocation sync)."
        VcsConnection.objects.create(
            workspace=ws,
            auth_mode=VcsConnection.AuthMode.GITHUB_APP,
            installation_id=4242,
            status=VcsConnection.Status.DISABLED,
            last_error=note,
        )

        statuses = reader.list_statuses(workspace_id=str(ws.id))

        assert len(statuses) == 1
        status = statuses[0]
        assert status.status == VcsConnection.Status.DISABLED
        assert "deleted on GitHub" in status.last_error

    def test_legacy_github_connection_rows_are_not_double_counted(self, reader, workspace_factory):
        """Migration 0008 copied every ``GitHubConnection`` row into ``VcsConnection``
        preserving the id. The reader inventories ONLY ``VcsConnection`` — a migrated
        pair must appear exactly once, and a (hypothetical) unmigrated legacy row is
        deliberately not reported (the model is deprecated and write-dead)."""
        ws = workspace_factory()
        legacy = GitHubConnection.objects.create(
            workspace=ws,
            name="GitHub",
            repo_allowlist=["acme/app"],
            token_ciphertext=_SECRET_CIPHERTEXT,
            status=GitHubConnection.Status.CONNECTED,
        )
        # The migrated twin (same id — migration 0008 preserves identity).
        VcsConnection.objects.create(
            id=legacy.id,
            workspace=ws,
            provider=VcsConnection.Provider.GITHUB,
            name=legacy.name,
            repo_allowlist=legacy.repo_allowlist,
            token_ciphertext=legacy.token_ciphertext,
            status=legacy.status,
        )

        statuses = reader.list_statuses(workspace_id=str(ws.id))

        assert len(statuses) == 1
        assert statuses[0].id == str(legacy.id)

    def test_read_is_workspace_scoped(self, reader, workspace_factory):
        ws_a = workspace_factory()
        ws_b = workspace_factory()
        VcsConnection.objects.create(
            workspace=ws_b,
            name="Other-WS GitHub",
            token_ciphertext=_SECRET_CIPHERTEXT,
            status=VcsConnection.Status.CONNECTED,
        )

        statuses = reader.list_statuses(workspace_id=str(ws_a.id))

        # ws_a has no connections — ws_b's secret-bearing row never leaks.
        assert statuses == []
