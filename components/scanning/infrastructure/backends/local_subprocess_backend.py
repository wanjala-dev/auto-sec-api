"""LocalSubprocessBackend — run the engine as a fixed-argv, no-shell subprocess.

The dev/CI backend (ADR 0006 D2). Isolation here is the worker's own sandbox (a
dedicated hardened container / gVisor `runsc` on a single node); this class's job is a
*safe invocation*: no ``shell=True`` (never command-injectable), creds passed via env
NOT argv (``/proc`` is world-readable), ``AWS_EC2_METADATA_DISABLED=true`` (no metadata
pivot / fail-fast on bad creds), and a hard timeout. The K8sJobBackend is the production
substrate; this keeps the whole path unit-testable without a cluster.
"""

from __future__ import annotations

import logging
import os
import subprocess

from components.scanning.application.ports.scan_execution_backend import (
    ProgressCallback,
    ScanExecutionBackend,
    ScanJobResult,
    ScanJobSpec,
)

logger = logging.getLogger(__name__)


class LocalSubprocessBackend(ScanExecutionBackend):
    def run(self, spec: ScanJobSpec, *, on_progress: ProgressCallback | None = None) -> ScanJobResult:
        # The image is irrelevant locally — the engine binary is on the worker's PATH.
        # argv[0] is the binary (e.g. "trivy" / "prowler"); the rest is the fixed argv.
        env = {
            **os.environ,
            **spec.env,
            **spec.secret_env,
            # A scan must never use the worker's ambient identity, and a bad-creds scan
            # must fail fast rather than hang on the metadata timeout.
            "AWS_EC2_METADATA_DISABLED": "true",
        }
        try:
            proc = subprocess.run(
                list(spec.args),
                env=env,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("scan_subprocess timed out source=%s", spec.source)
            return ScanJobResult(stdout="", exit_code=124, timed_out=True)
        except FileNotFoundError:
            logger.exception("scan_subprocess binary not found source=%s argv0=%s", spec.source, spec.args[0])
            return ScanJobResult(stdout="", exit_code=127)

        if proc.returncode != 0:
            # stderr may carry the engine's error; log it (never the creds env).
            logger.warning(
                "scan_subprocess nonzero source=%s exit=%s stderr=%s",
                spec.source,
                proc.returncode,
                (proc.stderr or "")[:500],
            )
        return ScanJobResult(stdout=proc.stdout or "", exit_code=proc.returncode)
