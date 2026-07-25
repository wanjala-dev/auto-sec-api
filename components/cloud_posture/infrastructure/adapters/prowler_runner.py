"""Run Prowler against a customer account and return OCSF records.

``run_prowler`` drives Prowler via its **Python SDK** through a standalone
runner script (``prowler_sdk_runner.py``) executed by the dedicated Prowler
venv's interpreter (``PROWLER_VENV_PYTHON``) — Prowler stays dep-isolated from
Django, and we get **real per-check progress** (the SDK's ``Scan.scan()``
generator) streamed back as JSON lines while the OCSF file it writes is parsed
unchanged. Credentials are already-assumed, short-lived creds vended by the
integrations token-vending seam; this module never assumes roles itself.

Isolated so the task can be tested without AWS or a Prowler install (tests mock
the subprocess). Returns ``[]`` if the runner produced no OCSF output.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from django.conf import settings

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 1800


def run_prowler(
    *,
    credentials: dict,
    account_id: str,
    regions: list[str] | None = None,
    progress_callback: Callable[[float], None] | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> list[dict]:
    """Run Prowler (SDK) with the assumed creds; return parsed OCSF records.

    Streams real per-check progress to ``progress_callback`` (a float 0–100) as
    the SDK yields it. Returns ``[]`` if the runner produced no OCSF output
    (e.g. a run error) — the caller records an empty scan rather than crashing
    the beat cycle.
    """
    venv_python = getattr(settings, "PROWLER_VENV_PYTHON", "python")
    script = os.path.join(os.path.dirname(__file__), "prowler_sdk_runner.py")
    env = {
        **os.environ,
        "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
        "AWS_SESSION_TOKEN": credentials["SessionToken"],
        # A scan must use ONLY the assumed creds above — never the worker's
        # ambient identity. Disabling the metadata fallback both enforces that
        # and makes a bad-creds scan fail fast instead of hanging on the EC2
        # metadata timeout.
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    with tempfile.TemporaryDirectory() as out_dir:
        out_file = os.path.join(out_dir, f"prowler-{account_id}.ocsf.json")
        cmd = [venv_python, script, account_id, ",".join(regions or []), out_file]

        proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            for line in proc.stdout or []:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue  # not a protocol line (stray stdout)
                kind = msg.get("t")
                if kind == "progress" and progress_callback is not None:
                    try:
                        progress_callback(float(msg.get("pct") or 0.0))
                    except Exception:  # noqa: BLE001 — a UI update must never fail the scan
                        logger.exception("prowler progress_callback failed account=%s", account_id)
                elif kind == "error":
                    logger.error("prowler_sdk_error account=%s message=%s", account_id, msg.get("message"))
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.warning("prowler run timed out account=%s", account_id)
            return []

        # The runner appends a `.ocsf.json` suffix; glob so we match regardless
        # of the exact naming convention.
        matches = sorted(Path(out_dir).glob("*.ocsf.json"))
        if not matches:
            logger.warning("prowler produced no OCSF output account=%s", account_id)
            return []
        data = json.loads(matches[0].read_text())
    return data if isinstance(data, list) else []
