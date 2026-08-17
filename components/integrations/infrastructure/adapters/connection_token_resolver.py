"""Per-connection VCS credential resolution — the ONE auth-strategy seam.

Every consumer that needs a runtime token for a ``VcsConnection`` (the draft-PR
open, the merge-check read, the SAST scan vend, connection verify, the patch
backfill) resolves it HERE instead of decrypting ``token_ciphertext`` inline, so
the credential strategy cannot fork per call site (dry-reuse):

* ``auth_mode == "pat"`` (default, Phase A) — decrypt the stored PAT via the
  integrations Fernet envelope. Byte-for-byte the historical behavior.
* ``auth_mode == "github_app"`` (ADR 0010 Phase B) — mint/fetch a short-lived
  installation token from :mod:`github_app_auth`. The stored ciphertext is
  deliberately NEVER read in this mode: no user PAT is touched, and the PR the
  token opens is authored by the app's bot identity.

Returns ``""`` for "no credential available" (missing ciphertext / missing
installation id) — the callers' existing no-token gates handle that. Raises the
typed :class:`~.vcs.github_app_auth.GitHubAppInstallationRevokedError` /
``GitHubAppNotConfiguredError`` (both :class:`VcsApiError` subclasses) so the
connection layer can act on a revoked installation instead of seeing a generic
failure.
"""

from __future__ import annotations

from django.views.decorators.debug import sensitive_variables

AUTH_MODE_PAT = "pat"
AUTH_MODE_GITHUB_APP = "github_app"


@sensitive_variables("token")
def resolve_connection_token(connection) -> str:
    """Resolve the runtime token for ``connection`` per its ``auth_mode``."""
    if connection is None:
        return ""

    auth_mode = (getattr(connection, "auth_mode", "") or AUTH_MODE_PAT).strip().lower()
    if auth_mode == AUTH_MODE_GITHUB_APP:
        installation_id = getattr(connection, "installation_id", None)
        if not installation_id:
            return ""
        from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
            get_installation_token,
        )

        return get_installation_token(installation_id)

    from components.integrations.infrastructure.adapters.secret_envelope import decrypt_secret

    return decrypt_secret(getattr(connection, "token_ciphertext", "") or "")
