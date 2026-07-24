"""Run Prowler against a customer account and return OCSF records.

Two seams, both isolated so the orchestration task can be tested without AWS or
a Prowler install:

* ``assume_account_credentials`` — assume the read-only audit role IN the target
  member account (the StackSet deploys the role to every account) with the
  confused-deputy ``ExternalId``. Mirrors the integrations assume-role posture.
* ``run_prowler`` — invoke the Prowler CLI (Apache-2.0) with the assumed creds,
  emit OCSF JSON, and read it back. The live run needs Prowler installed + the
  operator's IAM audit-role rollout; tests mock this function.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 1800


def assume_account_credentials(
    *,
    account_id: str,
    role_name: str,
    external_id: str,
    session_name: str = "autosec-prowler",
    duration_seconds: int = 3600,
) -> dict:
    """Assume ``arn:aws:iam::<account_id>:role/<role_name>``; return STS creds."""
    import boto3

    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    creds = boto3.client("sts").assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
        ExternalId=external_id,
        DurationSeconds=duration_seconds,
    )["Credentials"]
    logger.info("cloud_posture_role_assumed account=%s role=%s", account_id, role_name)
    return creds


def run_prowler(
    *,
    credentials: dict,
    account_id: str,
    regions: list[str] | None = None,
    prowler_bin: str = "prowler",
    timeout: int = _DEFAULT_TIMEOUT,
) -> list[dict]:
    """Run Prowler with the assumed creds and return parsed OCSF finding records.

    Returns ``[]`` if Prowler produced no output file (e.g. a run error) — the
    caller records an empty scan rather than crashing the beat cycle.
    """
    env = {
        **os.environ,
        "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
        "AWS_SESSION_TOKEN": credentials["SessionToken"],
    }
    with tempfile.TemporaryDirectory() as out_dir:
        filename = f"prowler-{account_id}"
        cmd = [
            prowler_bin,
            "aws",
            "--output-formats",
            "json-ocsf",
            "--output-directory",
            out_dir,
            "--output-filename",
            filename,
            # Prowler exits 3 when findings are present — not an execution error.
            "--ignore-exit-code-3",
        ]
        if regions:
            cmd += ["--region", *regions]

        subprocess.run(cmd, env=env, timeout=timeout, check=False, capture_output=True)

        path = os.path.join(out_dir, f"{filename}.ocsf.json")
        if not os.path.exists(path):
            logger.warning("prowler produced no output account=%s", account_id)
            return []
        with open(path) as handle:
            data = json.load(handle)
    return data if isinstance(data, list) else []
