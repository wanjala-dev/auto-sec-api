"""TrivyScanner — the container-SCA ScannerPort adapter (ADR 0006 D4).

Knows *what* to run (the Trivy invocations) and how to parse them; delegates *where*
they run to the injected ``ScanExecutionBackend`` (subprocess in dev, an ephemeral
gVisor Job in prod). Points Trivy's client at the ``trivy-server`` (gRPC) for the vuln
DB, so scan Jobs never download it. The untrusted image ref is validated (D5) and
always passed as a positional shell parameter (``"$1"``) — never interpolated into
the script text — and always after ``--`` in each trivy argv.

The Job runs a small POSIX-sh script with TWO trivy invocations against the same
warm cache:

1. the vuln scan (``--format json --scanners vuln``) — byte-identical output to the
   pre-SBOM pipeline; a non-zero exit fails the whole scan, loud (unchanged), and
2. a CycloneDX SBOM pass (``--format cyclonedx``) — image analysis is already cached
   from pass 1 so this is fast. Trivy has no dual-format single invocation
   (``trivy convert`` exists precisely because of that, but it requires the vuln
   JSON to carry ``--list-all-pkgs``, which would bloat the vuln report with every
   package; the second cache-warm pass keeps the vuln output unchanged instead).

Both outputs return to the worker on the Job's only channel — stdout — as ONE JSON
envelope: ``{"autosec_trivy_envelope": 1, "vuln": {...}, "sbom": {...}|null}``.
SBOM POLICY: a failed SBOM pass never fails the vuln scan — the envelope carries
``"sbom": null`` and the adapter logs a warning (an honest absent state); only the
vuln pass is fail-loud.
"""

from __future__ import annotations

from dataclasses import replace

import json
import logging
import os
import re

from components.container_security.domain.image_reference import validate_image_reference
from components.container_security.infrastructure.services.trivy_normalizer import (
    trivy_json_to_scan_result,
)
from components.scanning.application.ports.scan_execution_backend import (
    SCAN_ARTIFACT_PATH,
    ScanExecutionBackend,
    ScanJobSpec,
    artifact_emit_tail,
)
from components.scanning.domain.engine_output import parse_engine_result_document
from components.scanning.domain.errors import IncompleteScanOutputError, ScanExecutionError
from components.shared_kernel.application.ports.scanner_port import (
    ProgressCallback,
    ScanArtifact,
    ScannerPort,
    ScanResult,
    ScanTarget,
)

logger = logging.getLogger(__name__)

# The scanner image the K8sJobBackend runs (LocalSubprocessBackend ignores it — `trivy`
# is on the worker PATH). Pinned by version AND digest (we execute this image —
# pin-versions.md rule #2; the multi-arch manifest-list digest for 0.58.0, resolved
# 2026-08-07 — a re-pushed tag can no longer change what we run).
_TRIVY_IMAGE = os.environ.get(
    "TRIVY_IMAGE",
    "aquasec/trivy:0.58.0@sha256:b88012e2a0a309d6a8a00463d4e63e5e513377fb74eccbc8f9b0f8f81940ebeb",
)

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
# it also covers scanner-image pull + pod scheduling/startup (and now the fast cache-warm
# SBOM pass after the vuln pass).
#
# INVARIANT (the deadline relationship): backend timeout = trivy --timeout + this headroom,
# so it strictly OUTLIVES Trivy. A genuinely slow scan is ended by Trivy itself — a clean,
# fail-loud non-zero exit the adapter raises on — never by the Job deadline killing the pod
# mid-scan (which would lose the engine's error output).
_BACKEND_TIMEOUT_HEADROOM_SECONDS = 300

_GO_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")

# The artifact kind + media type the SBOM travels under (interpreted by the
# container_security post-ingest hook — the generic pipeline never inspects it).
SBOM_ARTIFACT_KIND = "sbom.cyclonedx"
SBOM_MEDIA_TYPE = "application/vnd.cyclonedx+json"

_ENVELOPE_KEY = "autosec_trivy_envelope"

# The engine name used in fail-loud output-integrity errors.
_ENGINE_NAME = "trivy"

# The in-Job orchestration script. POSIX sh (the pinned aquasec/trivy image is
# alpine-based → busybox sh at /bin/sh). SECURITY: only trusted, validated config is
# interpolated into the script text ({timeout} is regex-validated, {server} comes from
# our own env); the UNTRUSTED image ref rides exclusively as the positional "$1".
# stderr of both passes is captured to a file so the pod log / stdout carries ONLY the
# JSON envelope; on a vuln-pass failure the captured stderr is replayed to stdout so
# the fail-loud path keeps its diagnostics (the adapter logs a stdout snippet).
_JOB_SCRIPT_TEMPLATE = """\
set -u
vuln_out=/tmp/autosec-trivy-vuln.json
sbom_out=/tmp/autosec-trivy-sbom.cdx.json
errlog=/tmp/autosec-trivy-stderr.log
trivy --cache-dir "$TRIVY_CACHE_DIR" --timeout {timeout} image --format json \
    --scanners vuln --quiet --output "$vuln_out"{server} -- "$1" 2>"$errlog"
code=$?
if [ "$code" -ne 0 ]; then
  cat "$errlog"
  exit "$code"
fi
sbom_ok=1
if ! trivy --cache-dir "$TRIVY_CACHE_DIR" --timeout {timeout} image --format cyclonedx \
    --quiet --output "$sbom_out" -- "$1" >>"$errlog" 2>&1; then
  sbom_ok=0
fi
envelope=/tmp/autosec-trivy-envelope.json
{{
  printf '{{"{envelope_key}":1,"vuln":'
  cat "$vuln_out"
  if [ "$sbom_ok" -eq 1 ]; then
    printf ',"sbom":'
    cat "$sbom_out"
  else
    printf ',"sbom":null'
  fi
  printf '}}\\n'
}} > "$envelope"
code=0
{artifact_tail}cat "$envelope"
"""


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


def _job_script(*, timeout: str, server: str | None) -> str:
    """Render the in-Job sh script from TRUSTED config only (the ref stays "$1").

    ``timeout`` has already passed ``_duration_seconds`` (strict regex — no shell
    metacharacters can survive it). ``server`` is our own deployment config
    (TRIVY_SERVER_URL), not request input; it is still character-guarded because a
    config typo must fail loud here, not inject into the script.
    """
    server_fragment = ""
    if server:
        if re.search(r"[\s'\"\\$`;|&<>()]", server):
            raise ScanExecutionError(f"Invalid TRIVY_SERVER_URL {server!r} (unsafe characters)")
        server_fragment = f" --server {server}"
    return _JOB_SCRIPT_TEMPLATE.format(
        timeout=timeout,
        server=server_fragment,
        envelope_key=_ENVELOPE_KEY,
        # The shared artifact protocol (ADR 0022) — rendered, never hand-rolled, so all
        # three engines publish their result identically.
        artifact_tail=artifact_emit_tail("$envelope"),
    )


class TrivyScanner(ScannerPort):
    def __init__(self, backend: ScanExecutionBackend):
        self._backend = backend

    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        allowed = target.params.get("allowed_registries")
        image_ref = validate_image_reference(target.identifier, allowed_registries=allowed)

        trivy_timeout = _trivy_scan_timeout()
        script = _job_script(timeout=trivy_timeout, server=os.environ.get("TRIVY_SERVER_URL"))
        # Fixed argv, no interpolation of the ref: the script is a literal argument,
        # "autosec-trivy" is $0, and the validated-but-untrusted ref is $1 — it can
        # never be parsed as script text.
        args = ("/bin/sh", "-c", script, "autosec-trivy", image_ref)

        result = self._backend.run(
            ScanJobSpec(
                source="container_security.trivy",
                image=_TRIVY_IMAGE,
                # A writable cache home for the read-only-rootfs Job (see _TRIVY_CACHE_DIR).
                env={"TRIVY_CACHE_DIR": _TRIVY_CACHE_DIR, "HOME": "/tmp"},
                args=args,
                # ECR pull creds (if any) — mounted as env in the Job, never in argv/logs.
                secret_env=_aws_secret_env(target.credentials),
                # Backend deadline (k8s Job activeDeadlineSeconds / subprocess timeout) MUST
                # outlive Trivy's own --timeout — see _BACKEND_TIMEOUT_HEADROOM_SECONDS.
                timeout_seconds=_duration_seconds(trivy_timeout) + _BACKEND_TIMEOUT_HEADROOM_SECONDS,
                # Raw output travels as an object-storage artifact, not pod-log stdout (ADR 0022).
                artifact_path=SCAN_ARTIFACT_PATH,
                workspace_id=str(target.params.get("workspace_id") or ""),
                scan_run_id=str(target.params.get("scan_run_id") or ""),
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

        vuln_payload, sbom_content = _split_envelope(result.stdout, image_ref=image_ref)
        scan_result = replace(
            trivy_json_to_scan_result(vuln_payload, image_ref=image_ref),
            raw_artifact_ref=result.artifact_ref,  # ADR 0022 D2
        )
        if sbom_content is None:
            return scan_result
        artifact = ScanArtifact(kind=SBOM_ARTIFACT_KIND, media_type=SBOM_MEDIA_TYPE, content=sbom_content)
        # ``replace``, NOT a rebuilt ScanResult: hand-listing the fields silently dropped
        # ``raw_artifact_ref`` here (caught only by a live scan — the run completed with an
        # empty artifact reference). Copying a frozen dataclass field-by-field means every
        # future field has to be remembered in this one spot; replace() cannot forget.
        return replace(scan_result, artifacts=(artifact,))


def _split_envelope(stdout: str, *, image_ref: str) -> tuple[str | dict, str | None]:
    """Split the Job's stdout envelope into (vuln payload, SBOM JSON text or None).

    Fails LOUD on an unusable document: this used to hand non-JSON stdout straight to the
    normalizer, which "leniently" turned it into zero findings — so a truncated envelope
    (the vuln report is the bulk of the bytes, and a fat image's report is large) recorded a
    COMPLETED run over a mutilated result. ``parse_engine_result_document`` raises
    ``IncompleteScanOutputError`` instead (see that module for the full rationale).

    Tolerance kept where it is correct: legacy plain-Trivy JSON (no envelope) is still
    treated as the vuln report, a clean image's well-formed envelope with no
    vulnerabilities still completes normally, and the normalizer keeps its leniency for
    individual malformed records inside a well-formed document. SBOM POLICY (honest absent
    state) is unchanged: ``"sbom": null`` → warn + return None; the vuln pipeline continues.
    """
    data = parse_engine_result_document(stdout, engine=_ENGINE_NAME)
    if not isinstance(data, dict):
        # A top-level array is never a Trivy report (envelope or legacy) — unusable, not empty.
        raise IncompleteScanOutputError(
            f"Trivy output for {image_ref} is a JSON {type(data).__name__}, expected the "
            f"envelope object (or a legacy plain-Trivy report object)."
        )
    if data.get(_ENVELOPE_KEY) != 1:
        return data, None  # legacy plain-Trivy JSON: the whole payload IS the vuln report

    vuln = data.get("vuln")
    sbom = data.get("sbom")
    if not isinstance(sbom, dict) or not sbom:
        logger.warning("trivy_sbom_absent image=%s (SBOM pass failed or emitted nothing)", image_ref)
        return vuln if isinstance(vuln, dict) else {}, None
    return vuln if isinstance(vuln, dict) else {}, json.dumps(sbom, separators=(",", ":"))


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
