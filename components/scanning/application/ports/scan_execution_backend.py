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

# ── The Job-side artifact protocol (ADR 0022 D2) ────────────────────────────────────
# Defined ONCE, here, because it is the contract between two things that must agree
# exactly: the engine script (which writes) and the backend's uploader co-container
# (which ships). Three engines speaking three dialects of this would be the per-engine
# transport the design exists to avoid — so every adapter renders its emit step from
# ``artifact_emit_tail`` rather than hand-rolling one.
SCAN_ARTIFACT_PATH = "/tmp/autosec-scan-result.json"
SCAN_SENTINEL_PATH = "/tmp/.autosec-scan-complete"


def artifact_emit_tail(source_path: str) -> str:
    """Render the sh tail every engine script ends with to publish its result.

    ``source_path`` is the file the engine's own CLI wrote — the ONLY thing that differs
    per engine, because each tool names its output its own way. Everything after this
    point (upload, fetch, size caps, failure semantics) is shared machinery.

    It publishes the document to the canonical artifact path and then writes the engine's
    exit code to the sentinel, in that order. The order is the correctness bit: the
    uploader waits on the sentinel, so the artifact is always complete before anything
    can observe that it is ready — no torn read, no racing a half-written file.

    Callers must interpolate this into a script that captured the engine's exit status in
    ``$code`` first.
    """
    return (
        f'if [ "$code" = "0" ] && [ -s "{source_path}" ]; then '
        f'cp "{source_path}" "{SCAN_ARTIFACT_PATH}"; fi; '
        f'printf "%s" "$code" > "{SCAN_SENTINEL_PATH}"; '
    )


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
    # The container memory limit (a k8s quantity string, e.g. "2Gi"). Default suits the light
    # engines (Trivy reads a local image tarball). A heavy engine that loads every provider SDK
    # and enumerates a whole account in-memory (Prowler, all regions) overrides it upward — at
    # 2Gi a real Prowler account scan is OOMKilled and silently yields zero findings.
    memory_limit: str | None = None
    # ── The artifact output channel (ADR 0022 D2) ──────────────────────────────────────
    # Absolute path, inside the shared scratch volume, where the engine writes its result
    # DOCUMENT. When set, the backend transports the result as an object-storage artifact
    # instead of pod-log stdout — the transport that silently truncated at the kubelet's
    # 10Mi containerLogMaxSize, under-reporting exactly on the biggest accounts.
    #
    # It is ONE channel for every engine: what differs per engine is only which file its
    # CLI happens to write, so each adapter points this at that file. Everything after —
    # upload, fetch, size caps, failure semantics — is shared here. Empty keeps the legacy
    # stdout path (LocalSubprocessBackend, where a pipe has no such ceiling).
    artifact_path: str = ""
    # Identity the artifact is stored under, so a run's raw output is retrievable for
    # debugging/replay. Empty means "the backend picks an ephemeral key".
    workspace_id: str = ""
    scan_run_id: str = ""

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
    # Where the raw output was persisted, as "<bucket>/<key>" — set only when the run used
    # the artifact channel. Rides up to ``ScanRun.raw_artifact_ref`` so a run's untouched
    # engine output stays retrievable for debugging, support and (later) replay. Note the
    # adapter still parses ``stdout``: the artifact channel changes HOW the bytes travel,
    # not what an adapter does with them — which is what keeps it one channel and not a
    # per-engine rewrite.
    artifact_ref: str = ""

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
