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
import re

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

# Trivy's client-side scan deadline (Go duration, e.g. "15m", "1h", "900s"). Trivy's own
# default is a mere 5m — real-world fat images (node:18-bullseye, nginx:1.16.0) blow
# through it during layer analysis and die with exit_code=1 / "context deadline exceeded".
# We always pass it explicitly so the deadline is visible in the argv and overridable.
_TRIVY_SCAN_TIMEOUT_DEFAULT = "15m"

# Headroom the execution backend gets ON TOP of Trivy's own deadline. The backend timeout
# (k8s Job activeDeadlineSeconds / subprocess timeout) starts before Trivy's timer does —
# it also covers scanner-image pull + pod scheduling/startup.
#
# INVARIANT (the deadline relationship): backend timeout = trivy --timeout + this headroom,
# so it strictly OUTLIVES Trivy. A genuinely slow scan is ended by Trivy itself — a clean,
# fail-loud non-zero exit the adapter raises on — never by the Job deadline killing the pod
# mid-scan (which would lose the engine's error output).
_BACKEND_TIMEOUT_HEADROOM_SECONDS = 300

_GO_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def _trivy_scan_timeout() -> str:
    """The Trivy ``--timeout`` value — env-overridable, validated fail-loud."""
    value = os.environ.get("TRIVY_SCAN_TIMEOUT", _TRIVY_SCAN_TIMEOUT_DEFAULT).strip()
    _duration_seconds(value)  # validate eagerly; a bad env value must not reach the Job
    return value


def _duration_seconds(value: str) -> int:
    """Parse a Go-style duration ("15m", "1h30m", "900s") into seconds. Fail loud on garbage."""
    match = _GO_DURATION_RE.match(value)
    if not match or not any(match.groups()):
        raise ScanExecutionError(
            f"Invalid TRIVY_SCAN_TIMEOUT duration {value!r} (expected a Go duration, e.g. '15m', '1h30m', '900s')"
        )
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


class TrivyScanner(ScannerPort):
    def __init__(self, backend: ScanExecutionBackend):
        self._backend = backend

    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        allowed = target.params.get("allowed_registries")
        image_ref = validate_image_reference(target.identifier, allowed_registries=allowed)

        trivy_timeout = _trivy_scan_timeout()
        args = [
            "trivy",
            "--cache-dir",
            _TRIVY_CACHE_DIR,
            # Explicit scan deadline (see _TRIVY_SCAN_TIMEOUT_DEFAULT) — Trivy's implicit
            # 5m default is too short for fat real-world images.
            "--timeout",
            trivy_timeout,
            "image",
            "--format",
            "json",
            "--scanners",
            "vuln",
            "--quiet",
        ]
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
                # Backend deadline (k8s Job activeDeadlineSeconds / subprocess timeout) MUST
                # outlive Trivy's own --timeout — see _BACKEND_TIMEOUT_HEADROOM_SECONDS.
                timeout_seconds=_duration_seconds(trivy_timeout) + _BACKEND_TIMEOUT_HEADROOM_SECONDS,
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
