"""Run Prowler against a customer account and return OCSF records.

``run_prowler`` invokes the Prowler CLI (Apache-2.0) with already-assumed,
short-lived credentials — this module no longer assumes roles itself; the
orchestration task vends credentials through the single integrations
credential port (the AWS token-vending seam). It emits OCSF JSON and reads it
back. Isolated so the task can be tested without AWS or a Prowler install
(tests mock this function). The live run needs Prowler installed + the
operator's IAM audit-role rollout.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 1800


def run_prowler(
    *,
    credentials: dict,
    account_id: str,
    regions: list[str] | None = None,
    prowler_bin: str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> list[dict]:
    """Run Prowler with the assumed creds and return parsed OCSF finding records.

    ``prowler_bin`` defaults to the ``PROWLER_BIN`` setting (the dedicated
    cloud-posture worker points it at its isolated venv). Returns ``[]`` if
    Prowler produced no OCSF output (e.g. a run error) — the caller records an
    empty scan rather than crashing the beat cycle.
    """
    binary = prowler_bin or getattr(settings, "PROWLER_BIN", "prowler")
    env = {
        **os.environ,
        "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
        "AWS_SESSION_TOKEN": credentials["SessionToken"],
    }
    with tempfile.TemporaryDirectory() as out_dir:
        cmd = [
            binary,
            "aws",
            "--output-formats",
            "json-ocsf",
            "--output-directory",
            out_dir,
            "--output-filename",
            f"prowler-{account_id}",
            # Prowler exits 3 when findings are present — not an execution error.
            "--ignore-exit-code-3",
        ]
        if regions:
            cmd += ["--region", *regions]

        subprocess.run(cmd, env=env, timeout=timeout, check=False, capture_output=True)

        # Prowler appends a `.ocsf.json` suffix; glob so we match its exact naming
        # regardless of version (robust to the filename convention).
        matches = sorted(Path(out_dir).glob("*.ocsf.json"))
        if not matches:
            logger.warning("prowler produced no OCSF output account=%s", account_id)
            return []
        data = json.loads(matches[0].read_text())
    return data if isinstance(data, list) else []
