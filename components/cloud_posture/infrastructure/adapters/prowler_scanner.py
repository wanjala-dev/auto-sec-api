"""ProwlerScanner — the CSPM ScannerPort adapter (ADR 0006 D4).

Runs the **official Prowler image** with its **native `-M json-ocsf` CLI** and parses the OCSF it
emits — the same shape as ``TrivyScanner`` (build argv → ``ScanExecutionBackend`` → parse
``result.stdout``). It deliberately does NOT import Prowler's internal SDK API: the previous
``prowler_sdk_runner.py`` imported ``prowler.lib.*`` / ``AwsProvider`` ("verified in 5.36.0"), which
broke on every Prowler version bump and forced us to build+own an image. Pinning the maintained
official image and using the stable CLI removes that coupling (see ``improve-dont-replicate.md``).

Getting the OCSF out of an ephemeral Job: Prowler writes OCSF to a *file* (no stdout mode), and the
K8sJobBackend collects *stdout* — so the Job runs Prowler then ``cat``s the file to stdout. The only
interpolated inputs are the **regions**, strictly validated by ``validate_aws_scan_target`` (real
AWS region tokens only), which closes the shell-injection surface — the same "validate the untrusted
input, then it's safe in the command" gate Trivy uses for its image ref. Credentials are the
already-assumed short-lived creds, mounted as ``secret_env`` (never in argv or logs).

Scale note (ADR 0006 D4 follow-up): a full-account OCSF result can exceed pod-log limits and be
truncated (``records_to_scan_result`` then defensively yields fewer/zero findings). The fix — shared
for Trivy too — is an artifact/volume output channel on the backend rather than pod-log stdout.
"""

from __future__ import annotations

import json
import logging
import os

from components.cloud_posture.domain.aws_scan_target import validate_aws_scan_target
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
# The maintained official Prowler image (pinned for reproducible + supply-chain-controlled scans),
# like Trivy's aquasec/trivy pin. Override with PROWLER_IMAGE.
_PROWLER_IMAGE = os.environ.get(
    "PROWLER_IMAGE",
    # Pinned by version AND digest (we execute this image — pin-versions.md rule #2). Prowler 5.36.0.
    "toniblyx/prowler:5.36.0@sha256:d37ab7a1d49e56023cf7199b291ec833285e9f3431052fcc2df834f73d81c296",
)
# In the official image the CLI is a venv entrypoint, not on the default PATH; prepend it so the
# script finds `prowler` (and still works if a custom PROWLER_IMAGE has it on PATH).
_PROWLER_BIN_DIR = "/home/prowler/.venv/bin"
# The official image's non-root user (uid 1000); its venv binary is only reachable by that uid, so
# the scan Job must run as it — not the backend's default hardened uid. Stable for the pinned digest.
_PROWLER_UID = 1000


class ProwlerScanner(ScannerPort):
    def __init__(self, backend: ScanExecutionBackend):
        self._backend = backend

    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
            records_to_scan_result,
        )

        # Strict gate: only well-formed AWS tokens reach the command (regions are interpolated).
        _account, regions = validate_aws_scan_target(target.identifier, target.params.get("regions"))
        region_flag = f"--region {' '.join(regions)}" if regions else ""

        # Official Prowler writes OCSF to a file (no stdout mode) → run it, suppress its
        # progress/table output, then cat the OCSF file to stdout for the backend to collect.
        script = (
            f'export PATH="{_PROWLER_BIN_DIR}:$PATH"; '
            "prowler aws --output-formats json-ocsf --output-directory /tmp "
            f"--output-filename scan {region_flag} >/dev/null 2>&1; "
            "cat /tmp/*.ocsf.json 2>/dev/null"
        )

        result = self._backend.run(
            ScanJobSpec(
                source="cloud_posture.prowler",
                image=_PROWLER_IMAGE,
                args=("sh", "-c", script),  # regions validated above → no injection surface
                env={"HOME": "/tmp"},  # prowler config/cache under the writable /tmp (readOnlyRootFS)
                secret_env=_aws_secret_env(target.credentials),
                run_as_user=_PROWLER_UID,  # the official image's uid; the venv binary needs it
            ),
            on_progress=on_progress,  # K8s elapsed-time heartbeat (Prowler has no stdout progress)
        )
        return records_to_scan_result(_parse_ocsf_stdout(result.stdout), engine_version=_ENGINE)


def _parse_ocsf_stdout(stdout: str | None) -> list:
    """Defensively parse the OCSF JSON array Prowler wrote to stdout.

    Prowler's OCSF output has had validity bugs (prowler-cloud/prowler#3675) and pod-log stdout can
    truncate a large result — either way the JSON may not parse, so return ``[]`` rather than raise
    (``records_to_scan_result`` also skips individual malformed records)."""
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        logger.warning("prowler OCSF output was not valid JSON (bytes=%d)", len(text))
        return []
    return data if isinstance(data, list) else []


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
