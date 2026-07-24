"""Unit tests for the STS credential-vending adapter (no AWS).

Mocks ``boto3.client`` so we verify ARN construction, the role-chaining
duration cap, and the per-role session cache without calling STS.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from components.integrations.infrastructure.adapters.sts_credentials_adapter import (
    StsCredentialsAdapter,
)

pytestmark = pytest.mark.unit

_FUTURE = datetime.now(timezone.utc) + timedelta(hours=1)


def _creds(expiry: datetime = _FUTURE) -> dict:
    return {
        "AccessKeyId": "AKIA",
        "SecretAccessKey": "secret",
        "SessionToken": "token",
        "Expiration": expiry,
    }


def _sts_returning(creds: dict) -> MagicMock:
    client = MagicMock()
    client.assume_role.return_value = {"Credentials": creds}
    return client


def test_assume_role_builds_arn_and_caps_duration():
    sts = _sts_returning(_creds())
    with patch("boto3.client", return_value=sts) as m_client:
        out = StsCredentialsAdapter().assume_role(
            account_id="123456789012",
            role_name="AutoSecAuditRole",
            external_id="ext-1",
            duration_seconds=43200,
        )
    m_client.assert_called_once_with("sts")
    kwargs = sts.assume_role.call_args.kwargs
    assert kwargs["RoleArn"] == "arn:aws:iam::123456789012:role/AutoSecAuditRole"
    assert kwargs["ExternalId"] == "ext-1"
    # Capped at the 1h role-chaining ceiling even though 12h was requested.
    assert kwargs["DurationSeconds"] == 3600
    assert out["SessionToken"] == "token"


def test_cached_session_is_reused_within_ttl():
    sts = _sts_returning(_creds())
    adapter = StsCredentialsAdapter()
    with patch("boto3.client", return_value=sts):
        adapter.assume_role(account_id="1", role_name="R", external_id="e")
        adapter.assume_role(account_id="1", role_name="R", external_id="e")
    assert sts.assume_role.call_count == 1  # second call served from cache


def test_uncached_always_reassumes():
    sts = _sts_returning(_creds())
    adapter = StsCredentialsAdapter()
    with patch("boto3.client", return_value=sts):
        adapter.assume_role(account_id="1", role_name="R", external_id="e", use_cache=False)
        adapter.assume_role(account_id="1", role_name="R", external_id="e", use_cache=False)
    assert sts.assume_role.call_count == 2


def test_expiring_session_is_evicted_and_reassumed():
    near = datetime.now(timezone.utc) + timedelta(minutes=2)  # inside the 10m refresh margin
    sts = _sts_returning(_creds(expiry=near))
    adapter = StsCredentialsAdapter()
    with patch("boto3.client", return_value=sts):
        adapter.assume_role(account_id="1", role_name="R", external_id="e")
        adapter.assume_role(account_id="1", role_name="R", external_id="e")
    assert sts.assume_role.call_count == 2  # near-expiry is never served from cache
