"""ScanExecutionBackend — WHERE/HOW a scanner engine runs (ADR 0006, Concern C).

A scanner adapter (Trivy, Prowler) knows *what* to run (argv) and how to parse the
output; it must NOT know *where* it runs. This port is that seam: "run this engine
invocation in isolation, return its raw output." Implementations swap per environment
without touching the adapters — ``LocalSubprocessBackend`` (dev/CI) and ``K8sJobBackend``
(the ephemeral, gVisor-isolated per-scan Job substrate).

The spec carries a **fixed argv** (never a shell string) and separates ``secret_env``
(short-lived creds — mounted, never in argv or logs) from plain ``env``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

ProgressCallback = Callable[[float], None]


@dataclass(frozen=True)
class ScanJobSpec:
    source: str  # e.g. "container_security.trivy" — labels/names the run
    image: str  # the minimal scanner image
    args: tuple[str, ...]  # fixed argv; NEVER interpolated into a shell
    env: dict[str, str] = field(default_factory=dict)  # non-secret env
    secret_env: dict[str, str] = field(default_factory=dict)  # creds — mounted, not logged
    timeout_seconds: int = 1800

    def __post_init__(self) -> None:
        if not self.image:
            raise ValueError("ScanJobSpec.image is required")
        if not self.args:
            raise ValueError("ScanJobSpec.args is required")
        # Defense in depth: no arg may be a bare shell metacharacter payload. The argv is
        # passed literally (no shell), and the caller has already validated untrusted refs.
        if any(not isinstance(a, str) for a in self.args):
            raise ValueError("ScanJobSpec.args must all be strings")


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

    def run(self, spec: ScanJobSpec, *, on_progress: ProgressCallback | None = None) -> ScanJobResult:
        raise NotImplementedError
