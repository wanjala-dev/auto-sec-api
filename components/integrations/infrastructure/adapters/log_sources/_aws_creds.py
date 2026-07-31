"""Shared assume-role client for AWS-backed log sources (ADR 0008).

Both the S3 and CloudWatch adapters read through the customer's audit role (the
confused-deputy ``ExternalId`` posture). The assume-role + client construction
lives here ONCE so it is not copy-pasted per adapter (DRY; solve once). ``config``
carries the identity (``management_account_id`` / ``role_name`` / ``external_id``).
"""

from __future__ import annotations


def assume_role_client(config: dict, service: str, *, region: str | None = None):
    """Assume the customer's read role and return a boto3 client for ``service``."""
    import boto3

    creds = boto3.client("sts").assume_role(
        RoleArn=f"arn:aws:iam::{config['management_account_id']}:role/{config['role_name']}",
        RoleSessionName="autosec-logwatch",
        ExternalId=config["external_id"],
    )["Credentials"]
    kwargs = {
        "aws_access_key_id": creds["AccessKeyId"],
        "aws_secret_access_key": creds["SecretAccessKey"],
        "aws_session_token": creds["SessionToken"],
    }
    if region:
        kwargs["region_name"] = region
    return boto3.client(service, **kwargs)
