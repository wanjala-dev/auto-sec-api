"""TrivyScanner — the container-SCA ScannerPort adapter (ADR 0006 D4).

Knows *what* to run (the Trivy argv) and how to parse it; delegates *where* it runs to
the injected ``ScanExecutionBackend`` (subprocess in dev, an ephemeral gVisor Job in
prod). Points Trivy's client at the ``trivy-server`` (gRPC) for the vuln DB, so scan Jobs
never download it. The untrusted image ref is validated (D5) and always passed after
``--``.
"""

from __future__ import annotations

import logging
import os

from components.container_security.domain.image_reference import validate_image_reference
from components.container_security.infrastructure.services.trivy_normalizer import (
    trivy_json_to_scan_result,
)
from components.scanning.application.ports.scan_execution_backend import (
    ScanExecutionBackend,
    ScanJobSpec,
)
from components.scanning.domain.errors import ScanExecutionError
from components.shared_kernel.application.ports.scanner_port import (
    ProgressCallback,
    ScannerPort,
    ScanResult,
    ScanTarget,
)

logger = logging.getLogger(__name__)

# The scanner image the K8sJobBackend runs (LocalSubprocessBackend ignores it — `trivy`
# is on the worker PATH). Pin a version for reproducible + supply-chain-controlled scans.
_TRIVY_IMAGE = os.environ.get("TRIVY_IMAGE", "aquasec/trivy:0.58.0")

# Where Trivy caches (its main DB in non-server mode + the separate language/Java DB it
# ALWAYS downloads locally, even in --server mode). The hardened Job runs with a read-only
# root filesystem and mounts a writable emptyDir at /tmp, so Trivy MUST cache under /tmp —
# otherwise it defaults to $HOME/.cache (i.e. /.cache) and FATAL-errors with
# "mkdir /.cache: read-only file system" the moment a lang-DB (e.g. a jar) is analyzed.
_TRIVY_CACHE_DIR = os.environ.get("TRIVY_CACHE_DIR", "/tmp/.trivycache")


class TrivyScanner(ScannerPort):
    def __init__(self, backend: ScanExecutionBackend):
        self._backend = backend

    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        allowed = target.params.get("allowed_registries")
        image_ref = validate_image_reference(target.identifier, allowed_registries=allowed)

        args = ["trivy", "--cache-dir", _TRIVY_CACHE_DIR, "image", "--format", "json", "--scanners", "vuln", "--quiet"]
        server = os.environ.get("TRIVY_SERVER_URL")
        if server:
            args += ["--server", server]
        args += ["--", image_ref]  # end-of-flags: the validated ref can never be a flag

        result = self._backend.run(
            ScanJobSpec(
                source="container_security.trivy",
                image=_TRIVY_IMAGE,
                # A writable cache home for the read-only-rootfs Job (see _TRIVY_CACHE_DIR).
                env={"TRIVY_CACHE_DIR": _TRIVY_CACHE_DIR, "HOME": "/tmp"},
                args=tuple(args),
                # ECR pull creds (if any) — mounted as env in the Job, never in argv/logs.
                secret_env=_aws_secret_env(target.credentials),
            ),
            on_progress=on_progress,
        )
        # Fail LOUD, never silent. We do not set Trivy's --exit-code, so a non-zero exit (or a
        # timeout) is a genuine engine failure — its stdout is an error message, not scan JSON.
        # Parsing that would yield an empty result and record a COMPLETED run with 0 findings —
        # a crashed scan masquerading as a clean image. Raise so run_scan_and_ingest marks the
        # ScanRun FAILED and re-raises (ADR 0006 / no-shortcuts: a bad scan is a failed scan).
        if not result.ok:
            snippet = (result.stdout or "").strip().replace("\n", " ")[:300]
            logger.error(
                "trivy_scan_failed image=%s exit_code=%s timed_out=%s detail=%s",
                image_ref,
                result.exit_code,
                result.timed_out,
                snippet,
            )
            raise ScanExecutionError(
                f"Trivy scan of {image_ref} failed (exit_code={result.exit_code}, timed_out={result.timed_out})"
            )
        return trivy_json_to_scan_result(result.stdout, image_ref=image_ref)


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
