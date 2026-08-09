"""Composition root for the Vercel integration (ADR 0021 D2/D3).

Wires the connection lifecycle service (repository + API adapter + secret
envelope) and vends the scan credential envelope. ``vend_vercel_scan_credentials``
is the ONE vending path — it plugs into the scanning registry's
``credentials_factory`` seam (third use, after the AWS assume-role default and the
code_security VCS token), so no pillar-internal vending path exists (the
scanner-architecture audit's convergence nit). Provider files are the allowed slot
for own-context infrastructure imports.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class VercelScanCredentialsError(LookupError):
    """The scan's connection is missing, disabled, or has no usable token (fail closed)."""


def get_vercel_api_adapter(token: str):
    from components.integrations.infrastructure.adapters.vercel.vercel_api_adapter import (
        VercelApiAdapter,
    )

    return VercelApiAdapter(token)


def get_vercel_connection_service():
    """Composition root for the VercelConnection lifecycle service — wires the
    repository, the API adapter (for verify), and the secret envelope. Controllers
    resolve this and stay ORM/SDK/crypto-free."""
    from components.integrations.application.providers.secret_envelope_provider import (
        decrypt_secret,
        encrypt_secret,
    )
    from components.integrations.application.vercel_connection_service import (
        VercelConnectionService,
    )
    from components.integrations.infrastructure.repositories.vercel_connection_repository import (
        VercelConnectionRepository,
    )

    return VercelConnectionService(
        _repo=VercelConnectionRepository(),
        _resolve_adapter=get_vercel_api_adapter,
        _encrypt=encrypt_secret,
        _decrypt=decrypt_secret,
    )


def vend_vercel_scan_credentials(
    *, workspace_id, target_ref: str, connection_id=None, account_id: str = "", params: dict | None = None
) -> dict:
    """Decrypt the connection's token into the scan's opaque credential envelope.

    The scanning registry's ``CredentialsVendor`` for ``cloud_posture.prowler.vercel``
    — called by the generic ``run_scan`` task at scan time. Fail-closed re-checks:
    the connection must exist IN this workspace and not be disabled (a race with a
    disconnect/disable between trigger and scan must not scan an unconsented team).
    The token itself never leaves the envelope path (env-only in the Job, never
    argv, never logged).
    """
    from infrastructure.persistence.integrations.models import VercelConnection

    connection = VercelConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()
    if connection is None:
        raise VercelScanCredentialsError(f"no Vercel connection {connection_id} in workspace {workspace_id}")
    if connection.status == VercelConnection.Status.DISABLED:
        raise VercelScanCredentialsError(f"Vercel connection {connection.id} is disabled")

    from components.integrations.application.providers.secret_envelope_provider import decrypt_secret

    token = decrypt_secret(connection.token_ciphertext)
    if not token:
        raise VercelScanCredentialsError(f"Vercel connection {connection.id} has no stored token")
    return {"token": token}
