"""Composition root for the GitHub App surface (ADR 0010 D6 / Phase B).

The application-layer front door the thin controllers call for the install /
setup / webhook flow. Provider files are the sanctioned slot for own-context
infrastructure imports; every function here lazily reaches the
``github_app_auth`` adapter, the connection service, or the webhook Celery
tasks, so the controllers stay ORM/SDK/crypto-free.

Tenancy: the setup redirect and the webhook arrive with NO tenant host, so the
workspace's owning database is resolved from the (signed / signature-verified)
payload — a cross-alias scan, the ``resolve_db_alias_for_stripe_account`` shape
— and bound via ``integration_callback_scope`` (tenancy skill §3d).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Webhook events → the Celery task that handles them. Everything else is
#: ignored (the receiver answers 204). Kept as data so the routing is one
#: glanceable table, mirroring the registry style of ``vcs_provider``.
_HANDLED_WEBHOOK_EVENTS = ("installation", "installation_repositories", "pull_request")


class WorkspaceUnresolvedError(Exception):
    """The signed state named a workspace no configured database holds."""


# ── Install flow ──────────────────────────────────────────────────────────


def build_github_app_install_url(*, workspace_id: str, user_id: str) -> str:
    """Sign {workspace_id, user_id} into a state param and build the GitHub
    install URL. Raises the adapter's typed not-configured error when the app
    slug is absent (surfaced by the controller as a 409-style config error)."""
    from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
        build_install_url,
        sign_install_state,
    )

    state = sign_install_state(workspace_id=str(workspace_id), user_id=str(user_id))
    return build_install_url(state)


def parse_github_app_install_state(state: str) -> dict:
    """Validate + decode the setup redirect's state (raises
    ``InvalidInstallStateError`` with reason ``expired``/``invalid``)."""
    from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
        unsign_install_state,
    )

    return unsign_install_state(state)


def get_install_state_error() -> type[Exception]:
    """The typed state-validation error (lazy — keeps this module import-light)."""
    from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
        InvalidInstallStateError,
    )

    return InvalidInstallStateError


def bind_github_app_installation(*, workspace_id: str, installation_id: int, user_id: str | None = None):
    """Create/update the workspace's app-mode ``VcsConnection`` (idempotent).

    The workspace id comes from the SIGNED STATE only — never from the query
    string — and the owning database is resolved from it by a cross-alias scan
    before the write is bound (§3d). Raises :class:`WorkspaceUnresolvedError`
    when no configured database holds the workspace.
    """
    from components.integrations.application.providers.vcs_provider import (
        get_vcs_connection_service,
    )
    from components.integrations.infrastructure.adapters.workspace_alias_resolver import (
        alias_owning_workspace,
    )
    from components.shared_platform.application.providers.tenancy_scopes_provider import (
        integration_callback_scope,
    )

    alias = alias_owning_workspace(str(workspace_id))
    if alias is None:
        raise WorkspaceUnresolvedError(f"No configured database holds workspace {workspace_id}.")

    with integration_callback_scope(alias):
        connection = get_vcs_connection_service().bind_github_app_installation(
            workspace_id=str(workspace_id),
            installation_id=int(installation_id),
            created_by_id=str(user_id) if user_id else None,
        )
    logger.info(
        "github_app_installation_bound workspace_id=%s installation_id=%s connection_id=%s",
        workspace_id,
        installation_id,
        connection.id,
    )
    return connection


# ── Webhook plumbing ──────────────────────────────────────────────────────


def github_webhook_secret_configured() -> bool:
    from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
        is_webhook_secret_configured,
    )

    return is_webhook_secret_configured()


def verify_github_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
        verify_webhook_signature,
    )

    return verify_webhook_signature(raw_body, signature_header)


def route_github_app_webhook(event: str, payload: dict) -> dict | None:
    """Route one VERIFIED webhook onto its Celery task (IDs only, >100ms rule).

    Returns a small ``{"task": ..., ...}`` describing what was enqueued, or
    ``None`` for an event/action this receiver deliberately ignores. The
    signature was checked by the caller BEFORE the body was parsed; nothing
    here trusts the payload beyond extracting ids.
    """
    event = (event or "").strip()
    payload = payload if isinstance(payload, dict) else {}
    if event not in _HANDLED_WEBHOOK_EVENTS:
        return None

    if event == "installation":
        action = str(payload.get("action") or "")
        installation_id = ((payload.get("installation") or {}).get("id")) or 0
        if action in ("deleted", "suspend") and installation_id:
            from components.integrations.infrastructure.tasks.github_app_webhook_tasks import (
                sync_github_app_installation,
            )

            sync_github_app_installation.delay(installation_id=int(installation_id), action=action)
            return {"task": "sync_github_app_installation", "action": action}
        return None

    if event == "installation_repositories":
        action = str(payload.get("action") or "")
        installation_id = ((payload.get("installation") or {}).get("id")) or 0
        removed = [
            str(repo.get("full_name") or "")
            for repo in (payload.get("repositories_removed") or [])
            if isinstance(repo, dict) and repo.get("full_name")
        ]
        if action == "removed" and installation_id and removed:
            from components.integrations.infrastructure.tasks.github_app_webhook_tasks import (
                note_github_app_repositories_removed,
            )

            note_github_app_repositories_removed.delay(installation_id=int(installation_id), removed_repos=removed)
            return {"task": "note_github_app_repositories_removed", "removed": len(removed)}
        return None

    # pull_request: only a close-with-merge feeds the reconcile seam — a
    # closed-unmerged PR is an abandoned fix the reconciler must NOT capture.
    action = str(payload.get("action") or "")
    pull_request = payload.get("pull_request") or {}
    repo = str(((payload.get("repository") or {}).get("full_name")) or "")
    if action == "closed" and bool(pull_request.get("merged")) and repo:
        from components.integrations.infrastructure.tasks.github_app_webhook_tasks import (
            sync_merged_pull_request,
        )

        sync_merged_pull_request.delay(repo=repo)
        return {"task": "sync_merged_pull_request", "repo": repo}
    return None
