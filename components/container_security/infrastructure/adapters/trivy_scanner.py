"""TrivyScanner — the container-SCA ScannerPort adapter (ADR 0006 D4).

Knows *what* to run (the Trivy argv) and how to parse it; delegates *where* it runs to
the injected ``ScanExecutionBackend`` (subprocess in dev, an ephemeral gVisor Job in
prod). Points Trivy's client at the ``trivy-server`` (gRPC) for the vuln DB, so scan Jobs
never download it. The untrusted image ref is validated (D5) and always passed after
``--``.
"""

from __future__ import annotations

import os

from components.container_security.domain.image_reference import validate_image_reference
from components.container_security.infrastructure.services.trivy_normalizer import (
    trivy_json_to_scan_result,
)
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

# The scanner image the K8sJobBackend runs (LocalSubprocessBackend ignores it — `trivy`
# is on the worker PATH). Pin a version for reproducible + supply-chain-controlled scans.
_TRIVY_IMAGE = os.environ.get("TRIVY_IMAGE", "aquasec/trivy:0.58.0")


class TrivyScanner(ScannerPort):
    def __init__(self, backend: ScanExecutionBackend):
        self._backend = backend

    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        allowed = target.params.get("allowed_registries")
        image_ref = validate_image_reference(target.identifier, allowed_registries=allowed)

        args = ["trivy", "image", "--format", "json", "--scanners", "vuln", "--quiet"]
        server = os.environ.get("TRIVY_SERVER_URL")
        if server:
            args += ["--server", server]
        args += ["--", image_ref]  # end-of-flags: the validated ref can never be a flag

        result = self._backend.run(
            ScanJobSpec(
                source="container_security.trivy",
                image=_TRIVY_IMAGE,
                args=tuple(args),
                # ECR pull creds (if any) — mounted as env in the Job, never in argv/logs.
                secret_env=_aws_secret_env(target.credentials),
            ),
            on_progress=on_progress,
        )
        # Trivy exits non-zero when vulnerabilities are found IF --exit-code is set; we do
        # not set it, so a nonzero exit is a real error → empty result (logged by backend).
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
