"""ProwlerScanner — the CSPM ScannerPort adapter, on the shared execution backend (ADR 0006 D4).

Knows *what* to run (the Prowler SDK runner argv) and how to parse it (OCSF →
``NormalizedFinding``); delegates *where* it runs to the injected ``ScanExecutionBackend`` —
the same seam TrivyScanner uses. The runner streams a JSON-lines protocol on stdout
(``{"t":"progress"}`` per check batch, a final ``{"t":"result","records":[...]}``); the
backend forwards each line to ``on_output_line``, so live per-check progress is preserved on
the local backend and the records come back without a shared temp file (a Job pod's
filesystem is ephemeral). Credentials are already-assumed short-lived creds, mounted as
``secret_env`` — never in argv or logs.

Today the exercised path is the local backend on the dedicated cloud_posture worker (its
isolated Prowler venv). Running Prowler as a gVisor K8s Job additionally needs a Prowler
engine image with the runner baked in and invocable on PATH (and, for full-account OCSF, a
shared-volume/object-store output transport rather than pod-log stdout) — the remaining ADR
0006 infra piece, parallel to Trivy's staged rollout.
"""

from __future__ import annotations

import json
import logging
import os

from django.conf import settings

from components.scanning.application.ports.scan_execution_backend import (
    ScanExecutionBackend,
    ScanJobSpec,
)
from components.shared_kernel.application.ports.scanner_port import (
    ProgressCallback,
    ScannerPort,
    ScanResult,
    ScanTarget,
)

logger = logging.getLogger(__name__)

_ENGINE = "prowler"
# The engine image the K8sJobBackend would run (LocalSubprocessBackend ignores it — the
# Prowler venv python is argv[0]). The K8s Prowler image is a follow-up (see module docstring).
_PROWLER_IMAGE = os.environ.get("PROWLER_IMAGE", "autosec-prowler:local")
_RUNNER = os.path.join(os.path.dirname(__file__), "prowler_sdk_runner.py")


class ProwlerScanner(ScannerPort):
    def __init__(self, backend: ScanExecutionBackend):
        self._backend = backend

    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
            records_to_scan_result,
        )

        account_id = target.identifier
        regions = ",".join(target.params.get("regions") or [])
        venv_python = getattr(settings, "PROWLER_VENV_PYTHON", "python")
        # argv[3] == "-" → the runner emits OCSF records on stdout (no shared temp file).
        args = (venv_python, _RUNNER, account_id, regions, "-")

        captured: dict = {"records": []}

        def _on_line(line: str) -> None:
            line = line.strip()
            if not line:
                return
            try:
                msg = json.loads(line)
            except ValueError:
                return  # stray, non-protocol stdout
            kind = msg.get("t")
            if kind == "progress" and on_progress is not None:
                try:
                    on_progress(float(msg.get("pct") or 0.0))
                except Exception:
                    logger.exception("prowler progress callback failed account=%s", account_id)
            elif kind == "result":
                records = msg.get("records")
                captured["records"] = records if isinstance(records, list) else []
            elif kind == "error":
                logger.error("prowler_sdk_error account=%s message=%s", account_id, msg.get("message"))

        self._backend.run(
            ScanJobSpec(
                source="cloud_posture.prowler",
                image=_PROWLER_IMAGE,
                args=args,
                secret_env=_aws_secret_env(target.credentials),
            ),
            on_progress=on_progress,  # K8s elapsed-time heartbeat
            on_output_line=_on_line,  # local live per-check progress + record capture
        )
        return records_to_scan_result(captured["records"], engine_version=_ENGINE)


def _aws_secret_env(credentials: dict | None) -> dict[str, str]:
    if not credentials:
        return {}
    out: dict[str, str] = {}
    if credentials.get("AccessKeyId"):
        out["AWS_ACCESS_KEY_ID"] = credentials["AccessKeyId"]
    if credentials.get("SecretAccessKey"):
        out["AWS_SECRET_ACCESS_KEY"] = credentials["SecretAccessKey"]
    if credentials.get("SessionToken"):
        out["AWS_SESSION_TOKEN"] = credentials["SessionToken"]
    return out
