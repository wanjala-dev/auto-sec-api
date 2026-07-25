#!/usr/bin/env python
"""Standalone Prowler SDK runner — streams real per-check progress, writes OCSF.

This script is executed by the DEDICATED PROWLER VENV's Python
(``/opt/prowler/venv/bin/python``), NOT the Django worker's interpreter — it
imports ONLY ``prowler`` (which lives in that isolated venv) and the stdlib, so
the venv isolation the app relies on is preserved. The worker's
``prowler_runner.run_prowler`` invokes it as a subprocess and reads its stdout.

Protocol (one JSON object per line on stdout):
    {"t": "progress", "pct": <float 0-100>}   # after each check batch
    {"t": "done", "count": <int>}             # findings written to the OCSF file
    {"t": "error", "message": "<str>"}        # fatal — non-zero exit

Assumed AWS credentials arrive via the environment (AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN) — never long-lived keys. Argv:
    argv[1] = account_id (labelling only)
    argv[2] = comma-separated regions ("" = all enabled regions)
    argv[3] = output OCSF file path
"""

import json
import os
import sys


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    account_id = sys.argv[1] if len(sys.argv) > 1 else ""
    regions = [r for r in (sys.argv[2].split(",") if len(sys.argv) > 2 else []) if r]
    out_file = sys.argv[3] if len(sys.argv) > 3 else "prowler.ocsf.json"

    try:
        from prowler.lib.outputs.ocsf.ocsf import OCSF
        from prowler.lib.scan.scan import Scan
        from prowler.providers.aws.aws_provider import AwsProvider
    except Exception as exc:  # noqa: BLE001
        _emit({"t": "error", "message": f"prowler import failed: {exc}"})
        return 1

    try:
        # Constructing the provider authenticates the assumed session AND sets
        # the global provider the checks read from (verified in 5.36.0).
        provider = AwsProvider(
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
            regions=set(regions),
        )
        scan = Scan(provider)

        findings = []
        last_pct = -1.0
        for progress, batch in scan.scan():
            if batch:
                findings.extend(batch)
            # Emit only on a >=1% change — the check loop ticks ~hundreds of times.
            pct = float(progress or 0.0)
            if pct - last_pct >= 1.0 or pct >= 100.0:
                last_pct = pct
                _emit({"t": "progress", "pct": pct})

        # Write the OCSF file the worker's ingest already parses.
        OCSF(findings=findings, file_path=out_file).batch_write_data_to_file()
        _emit({"t": "done", "count": len(findings)})
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit({"t": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
