"""Composition root for the AWS account-access port."""

from __future__ import annotations

from components.integrations.application.ports.aws_account_access_port import (
    AwsAccountAccessPort,
)

_adapter: AwsAccountAccessPort | None = None


def get_aws_account_access_port() -> AwsAccountAccessPort:
    """Return the process-wide account-access adapter (connection → credentials)."""
    global _adapter
    if _adapter is None:
        from components.integrations.infrastructure.adapters.aws_account_access_adapter import (
            AwsAccountAccessAdapter,
        )

        _adapter = AwsAccountAccessAdapter()
    return _adapter
