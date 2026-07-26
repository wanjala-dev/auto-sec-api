"""LocalSubprocessBackend — run the engine as a fixed-argv, no-shell subprocess.

The dev/CI backend (ADR 0006 D2). Isolation here is the worker's own sandbox (a
dedicated hardened container / gVisor `runsc` on a single node); this class's job is a
*safe invocation*: no ``shell=True`` (never command-injectable), creds passed via env
NOT argv (``/proc`` is world-readable), ``AWS_EC2_METADATA_DISABLED=true`` (no metadata
pivot / fail-fast on bad creds), and a hard timeout. The K8sJobBackend is the production
substrate; this keeps the whole path unit-testable without a cluster.

When ``on_output_line`` is given, stdout is streamed line-by-line as the engine produces
it (so an engine that emits a live progress/result protocol on stdout — Prowler's SDK
runner — is observed in real time); otherwise the fast buffered path is used.
"""

from __future__ import annotations

import logging
import os
import subprocess

from components.scanning.application.ports.scan_execution_backend import (
    OutputLineCallback,
    ProgressCallback,
    ScanExecutionBackend,
    ScanJobResult,
    ScanJobSpec,
)

logger = logging.getLogger(__name__)


class LocalSubprocessBackend(ScanExecutionBackend):
    def run(
        self,
        spec: ScanJobSpec,
        *,
        on_progress: ProgressCallback | None = None,
        on_output_line: OutputLineCallback | None = None,
    ) -> ScanJobResult:
        # The image is irrelevant locally — the engine binary is on the worker's PATH.
        # argv[0] is the binary (e.g. "trivy" / a venv python); the rest is the fixed argv.
        env = {
            **os.environ,
            **spec.env,
            **spec.secret_env,
            # A scan must never use the worker's ambient identity, and a bad-creds scan
            # must fail fast rather than hang on the metadata timeout.
            "AWS_EC2_METADATA_DISABLED": "true",
        }
        if on_output_line is not None:
            return self._run_streaming(spec, env, on_output_line)

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

    def _run_streaming(
        self, spec: ScanJobSpec, env: dict[str, str], on_output_line: OutputLineCallback
    ) -> ScanJobResult:
        """Popen + iterate stdout: forward each line live AND accumulate it for the result."""
        lines: list[str] = []
        try:
            proc = subprocess.Popen(
                list(spec.args),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )
        except FileNotFoundError:
            logger.exception("scan_subprocess binary not found source=%s argv0=%s", spec.source, spec.args[0])
            return ScanJobResult(stdout="", exit_code=127)

        try:
            for line in proc.stdout or []:
                lines.append(line)
                try:
                    on_output_line(line.rstrip("\n"))
                except Exception:
                    logger.exception("scan_subprocess on_output_line failed source=%s", spec.source)
            proc.wait(timeout=spec.timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.warning("scan_subprocess timed out source=%s", spec.source)
            return ScanJobResult(stdout="".join(lines), exit_code=124, timed_out=True)

        exit_code = proc.returncode or 0
        if exit_code != 0:
            stderr = (proc.stderr.read() if proc.stderr else "") or ""
            logger.warning("scan_subprocess nonzero source=%s exit=%s stderr=%s", spec.source, exit_code, stderr[:500])
        return ScanJobResult(stdout="".join(lines), exit_code=exit_code)
