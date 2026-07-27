"""ScanExecutionBackend — WHERE/HOW a scanner engine runs (ADR 0006, Concern C).

A scanner adapter (Trivy, Prowler) knows *what* to run (argv) and how to parse the
output; it must NOT know *where* it runs. This port is that seam: "run this engine
invocation in isolation, return its raw output." Implementations swap per environment
without touching the adapters — ``LocalSubprocessBackend`` (dev/CI) and ``K8sJobBackend``
(the ephemeral, gVisor-isolated per-scan Job substrate).

The spec carries a **fixed argv** (never a shell string) and separates ``secret_env``
(short-lived creds — mounted, never in argv or logs) from plain ``env``.

Two optional callbacks let the caller observe a run:
- ``on_progress(pct)`` — a coarse 0–100 heartbeat (backends that can only see elapsed
  time, e.g. a K8s Job, drive this).
- ``on_output_line(line)`` — each stdout line as it is produced. An engine that streams a
  progress/result protocol on stdout (Prowler's SDK runner) parses live per-check progress
  and its final records from here, so no shared temp file is needed (a Job pod's filesystem
  is ephemeral). Backends that cannot stream mid-run MAY deliver the lines once, after the
  run completes; the full stdout is always returned on the result regardless.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from components.scanning.domain.errors import InvalidScanSpecError

ProgressCallback = Callable[[float], None]
OutputLineCallback = Callable[[str], None]


@dataclass(frozen=True)
class ScanJobSpec:
    source: str  # e.g. "container_security.trivy" — labels/names the run
    image: str  # the minimal scanner image
    args: tuple[str, ...]  # fixed argv; NEVER interpolated into a shell
    env: dict[str, str] = field(default_factory=dict)  # non-secret env
    secret_env: dict[str, str] = field(default_factory=dict)  # creds — mounted, not logged
    timeout_seconds: int = 1800
    # The non-root uid the engine container runs as. Default is the backend's hardened uid; an
    # engine whose official image ships its own non-root user (e.g. Prowler's uid 1000, whose venv
    # binary only its owner can reach) overrides it. Must be non-zero — never run a scan as root.
    run_as_user: int | None = None

    def __post_init__(self) -> None:
        if not self.image:
            raise InvalidScanSpecError("ScanJobSpec.image is required")
        if not self.args:
            raise InvalidScanSpecError("ScanJobSpec.args is required")
        # Defense in depth: no arg may be a bare shell metacharacter payload. The argv is
        # passed literally (no shell), and the caller has already validated untrusted refs.
        if any(not isinstance(a, str) for a in self.args):
            raise InvalidScanSpecError("ScanJobSpec.args must all be strings")
        if self.run_as_user is not None and self.run_as_user <= 0:
            raise InvalidScanSpecError("ScanJobSpec.run_as_user must be a non-root uid")


@dataclass(frozen=True)
class ScanJobResult:
    stdout: str  # the scanner's raw output (the adapter parses this)
    exit_code: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class ScanExecutionBackend:
    """Interface (structural): implement ``run`` to be an execution backend."""

    def run(
        self,
        spec: ScanJobSpec,
        *,
        on_progress: ProgressCallback | None = None,
        on_output_line: OutputLineCallback | None = None,
    ) -> ScanJobResult:
        raise NotImplementedError
