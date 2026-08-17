"""Celery tasks behind the GitHub App webhook receiver (ADR 0010 Phase B).

The receiver is thin — signature check, id extraction, enqueue — so everything
that touches the database or another service happens HERE, off the request path
(performance rule §7). Tasks take IDs only, are idempotent (re-delivery safe:
GitHub retries failed webhooks), and log entry + completion at INFO.

Tenancy (§3d/§3i): a webhook has no tenant host, so each task resolves the
owning database(s) FROM THE PAYLOAD ids by an explicit cross-alias
``.using(alias)`` scan (the ``resolve_db_alias_for_stripe_account`` shape —
offline aliases skipped, never fatal) and performs alias-pinned writes. The
merged-PR fan-out re-binds per alias via ``integration_callback_scope`` before
dispatching, so the reconcile task's tenancy headers carry the right customer.
"""

from __future__ import annotations

import logging

from celery import current_app, shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

#: The EXISTING merge-detection seam (dry-reuse): the remediation reconciler
#: task that merge-checks candidates through the integrations application layer
#: and drives resolved findings into the gated corpus. Dispatched BY NAME so
#: this context never imports another context's infrastructure.
_RECONCILE_TASK = "remediation.reconcile_applied_remediations"


def _aliases() -> list[str]:
    from django.conf import settings

    aliases = list(getattr(settings, "DATABASES", {}).keys())
    if "default" in aliases:
        aliases = ["default"] + [alias for alias in aliases if alias != "default"]
    return aliases


@shared_task(name="integrations.sync_github_app_installation", soft_time_limit=60, time_limit=90)
def sync_github_app_installation(installation_id: int, action: str) -> dict:
    """Revocation sync: the customer deleted/suspended the installation on GitHub.

    Deactivates every app-mode connection bound to ``installation_id`` (across
    all configured databases) and drops its cached installation token, so the
    revocation the customer performed on GitHub is reflected here immediately —
    not at the next failed token exchange.
    """
    from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
        invalidate_installation_token,
    )
    from infrastructure.persistence.integrations.models import VcsConnection

    logger.info("sync_github_app_installation started installation_id=%s action=%s", installation_id, action)
    invalidate_installation_token(installation_id)

    verb = "deleted" if action == "deleted" else "suspended"
    note = (
        f"GitHub App installation {installation_id} was {verb} on GitHub — "
        "connection deactivated (revocation sync). Reinstall the app to reconnect."
    )
    updated = 0
    for alias in _aliases():
        try:
            updated += (
                VcsConnection.objects.using(alias)
                .filter(
                    auth_mode=VcsConnection.AuthMode.GITHUB_APP,
                    installation_id=installation_id,
                )
                .exclude(status=VcsConnection.Status.DISABLED)
                .update(
                    status=VcsConnection.Status.DISABLED,
                    last_error=note,
                    updated_at=timezone.now(),
                )
            )
        except Exception:  # nosec B112 — an offline alias is skipped, never fatal
            logger.warning("sync_github_app_installation alias_unavailable alias=%s", alias)
            continue

    logger.info(
        "sync_github_app_installation completed installation_id=%s action=%s deactivated=%s",
        installation_id,
        action,
        updated,
    )
    return {"deactivated": updated}


@shared_task(name="integrations.note_github_app_repositories_removed", soft_time_limit=60, time_limit=90)
def note_github_app_repositories_removed(installation_id: int, removed_repos: list[str]) -> dict:
    """Repositories were removed from the installation — note it on the row.

    The connection stays CONNECTED (the installation itself is intact); the
    note surfaces in the panel so the operator reconciles the repo allowlist.
    The cached token is dropped so no caller keeps a grant GitHub narrowed.
    """
    from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
        invalidate_installation_token,
    )
    from infrastructure.persistence.integrations.models import VcsConnection

    removed = [str(repo) for repo in (removed_repos or []) if repo]
    logger.info(
        "note_github_app_repositories_removed started installation_id=%s removed=%s",
        installation_id,
        len(removed),
    )
    invalidate_installation_token(installation_id)

    note = (
        "GitHub reports repositories removed from the App installation: "
        f"{', '.join(removed)[:1500]}. Review the repo allowlist and re-verify."
    )
    noted = 0
    for alias in _aliases():
        try:
            noted += (
                VcsConnection.objects.using(alias)
                .filter(
                    auth_mode=VcsConnection.AuthMode.GITHUB_APP,
                    installation_id=installation_id,
                )
                .update(last_error=note[:2000], updated_at=timezone.now())
            )
        except Exception:  # nosec B112 — an offline alias is skipped, never fatal
            logger.warning("note_github_app_repositories_removed alias_unavailable alias=%s", alias)
            continue

    logger.info(
        "note_github_app_repositories_removed completed installation_id=%s noted=%s",
        installation_id,
        noted,
    )
    return {"noted": noted}


@shared_task(name="integrations.sync_merged_pull_request", soft_time_limit=120, time_limit=180)
def sync_merged_pull_request(repo: str) -> dict:
    """A PR in ``repo`` closed MERGED — accelerate the existing reconcile seam.

    Finds every workspace whose CONNECTED GitHub connection allowlists ``repo``
    and dispatches ``remediation.reconcile_applied_remediations`` for it — the
    exact task the beat schedule already runs. The reconciler re-verifies merge
    state against the host and owns every consent/idempotency gate, so this is
    purely a latency win (webhook-now instead of next-beat), never a parallel
    merge-detection path. The allowlist membership check runs in Python because
    JSONField containment is not portable to the SQLite test settings, and
    per-workspace connection counts are small.
    """
    repo = (repo or "").strip()
    logger.info("sync_merged_pull_request started repo=%s", repo)
    if not repo:
        return {"dispatched": 0}

    from components.shared_platform.application.providers.tenancy_scopes_provider import (
        integration_callback_scope,
    )
    from infrastructure.persistence.integrations.models import VcsConnection

    dispatched = 0
    for alias in _aliases():
        try:
            rows = list(
                VcsConnection.objects.using(alias)
                .filter(
                    provider=VcsConnection.Provider.GITHUB,
                    status=VcsConnection.Status.CONNECTED,
                )
                .values_list("workspace_id", "repo_allowlist")
            )
        except Exception:  # nosec B112 — an offline alias is skipped, never fatal
            logger.warning("sync_merged_pull_request alias_unavailable alias=%s", alias)
            continue

        workspace_ids = sorted({str(workspace_id) for workspace_id, allowlist in rows if repo in (allowlist or [])})
        for workspace_id in workspace_ids:
            # Bind the owning tenant BEFORE dispatching so before_task_publish
            # stamps the reconcile task's tenancy headers with the right
            # customer (§3i: Celery tasks carry the tenant explicitly).
            with integration_callback_scope(alias):
                current_app.send_task(_RECONCILE_TASK, kwargs={"workspace_id": workspace_id})
            dispatched += 1

    logger.info("sync_merged_pull_request completed repo=%s dispatched=%s", repo, dispatched)
    return {"dispatched": dispatched}
