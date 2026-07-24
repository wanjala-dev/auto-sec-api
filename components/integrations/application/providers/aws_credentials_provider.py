"""Composition root for the AWS credential-vending port.

The single seam other contexts' allowed layers use to obtain short-lived
assumed-role credentials — the onboarding verifier, the CDR log-ingest
pipeline, and the CSPM scanner all resolve credentials here. Provider files are
the allowed slot for own-context infrastructure imports (the composition root);
a module-level singleton keeps the STS per-role session cache warm across calls.
"""

from __future__ import annotations

from components.integrations.application.ports.aws_role_credentials_port import (
    AwsRoleCredentialsPort,
)

_adapter: AwsRoleCredentialsPort | None = None


def get_aws_credentials_port() -> AwsRoleCredentialsPort:
    """Return the process-wide AWS credential-vending adapter (session-cached)."""
    global _adapter
    if _adapter is None:
        from components.integrations.infrastructure.adapters.sts_credentials_adapter import (
            StsCredentialsAdapter,
        )

        _adapter = StsCredentialsAdapter()
    return _adapter
