"""OpengrepScanner — the SAST ScannerPort adapter (ADR 0019 D2/D6).

Knows *what* to run (the Opengrep invocation over an unpacked repo archive) and how
to parse it; delegates *where* it runs to the injected ``ScanExecutionBackend``
(subprocess in dev, an ephemeral hardened K8s Job in prod) — the exact TrivyScanner
shape. The engine is the pinned official Opengrep release binary baked into our
minimal image (the opengrep org publishes no container image, so the ADR's named
fallback applies: pinned base + sha256-pinned release binary — never a custom SDK
wrapper). Override with ``OPENGREP_IMAGE``.

The Job runs a small POSIX-sh script that:

1. fetches the repo **archive tarball at a resolved commit SHA** (one HTTPS call to
   the VCS host — no ``git`` binary, no credential helper; the short-lived read
   token rides ONLY in env, never argv),
2. unpacks it into the writable ``emptyDir`` (size-capped fetch; tar member names
   are sanitized by tar itself and the Job is isolated either way),
3. deletes any repo-side scanner config (``.semgrepignore`` — a repo must not be
   able to silence its own findings, D6) and writes OUR curated ruleset from env,
4. runs ``opengrep scan --sarif`` with our rules/excludes (``--disable-nosem``,
   ``--disable-version-check`` — nothing repo-side configures the scan, no
   phone-home), from inside the repo root so SARIF paths are repo-relative, and
5. emits ONE JSON envelope on stdout (the Trivy stdout-envelope precedent):
   ``{"autosec_opengrep_envelope": 1, "sarif": {...}}``.

SECURITY: only trusted, validated config is interpolated into the script text (our
exclude globs, numeric limits); the untrusted-ish values (archive URL) and the
secret (token) ride exclusively as env. The scanned code is DATA — Opengrep parses,
never builds or executes it.
"""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import urlparse

from components.code_security.domain.repo_reference import (
    validate_commit_sha,
    validate_repo_reference,
)
from components.code_security.infrastructure.services.opengrep_normalizer import (
    opengrep_sarif_to_scan_result,
)
from components.code_security.infrastructure.services.ruleset import load_ruleset_yaml
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

SOURCE = "code_security.opengrep"

# Our minimal engine image: pinned base + the sha256-pinned official Opengrep v1.26.0
# release binary (built from auto-sec-infra k8s/images/opengrep.Dockerfile — the org
# ships no container image, so tag+digest pinning happens at the build inputs).
_OPENGREP_IMAGE = os.environ.get("OPENGREP_IMAGE", "autosec-opengrep:1.26.0")

# Backend deadline (k8s Job activeDeadlineSeconds / subprocess timeout). Opengrep has
# no total-scan deadline flag (only per-file --timeout), so unlike Trivy's dual
# deadline the Job deadline IS the hard stop for a pathological repo.
_SCAN_TIMEOUT_SECONDS = int(os.environ.get("OPENGREP_SCAN_TIMEOUT_SECONDS", "900"))

# Repo-size guard (ADR 0019 D3): the archive fetch aborts past this cap — an honest
# failed scan, not an OOM. 200 MiB of *compressed* archive is far past ICP repo size.
_MAX_ARCHIVE_BYTES = int(os.environ.get("OPENGREP_MAX_ARCHIVE_BYTES", str(200 * 1024 * 1024)))

# Default path excludes (OUR config, never the repo's): vendored/generated trees.
_EXCLUDES = ("node_modules", "vendor", "dist", "build", ".git", "*.min.js")
_EXCLUDE_SAFE_RE = re.compile(r"^[A-Za-z0-9_.*-]+$")

_ENVELOPE_KEY = "autosec_opengrep_envelope"

_ARTIFACT_KIND_SCAN_META = "code_security.scan_meta"

# The engine name used in fail-loud output-integrity errors.
_ENGINE_NAME = "opengrep"

# The in-Job orchestration script. POSIX sh. Interpolations ({fetch_cap}, {excludes},
# {jobs}) are trusted constants validated below; ARCHIVE_URL/VCS_TOKEN/OPENGREP_RULES
# arrive via env and are only ever expanded quoted. Distinct exit codes: 20 = archive
# fetch failed, 21 = extraction failed; the engine's own exit codes pass through.
_JOB_SCRIPT_TEMPLATE = """\
set -u
err=/tmp/autosec-opengrep-stderr.log
src=/tmp/autosec-src
sarif_out=/tmp/autosec-opengrep.sarif.json
rules=/tmp/autosec-rules.yaml
mkdir -p "$src"
curl -sSfL --retry 2 --max-time 300 --max-filesize {fetch_cap} \
    -H "Authorization: Bearer $VCS_TOKEN" \
    -o /tmp/autosec-repo.tar.gz "$ARCHIVE_URL" 2>"$err" || {{ cat "$err"; exit 20; }}
tar -xzf /tmp/autosec-repo.tar.gz -C "$src" --strip-components=1 2>>"$err" || {{ cat "$err"; exit 21; }}
rm -f /tmp/autosec-repo.tar.gz
find "$src" -name .semgrepignore -type f -delete 2>>"$err"
printf '%s' "$OPENGREP_RULES" > "$rules"
cd "$src"
opengrep scan --sarif --quiet --disable-nosem --disable-version-check \
    --no-rewrite-rule-ids --jobs {jobs}{excludes} -f "$rules" -o "$sarif_out" . 2>>"$err"
code=$?
if [ "$code" -ne 0 ]; then
  cat "$err"
  exit "$code"
fi
envelope=/tmp/autosec-opengrep-envelope.json
{{
  printf '{{"{envelope_key}":1,"sarif":'
  cat "$sarif_out"
  printf '}}\\n'
}} > "$envelope"
code=0
{artifact_tail}cat "$envelope"
"""


def _job_script() -> str:
    """Render the in-Job sh script from TRUSTED config only (URL/token/rules stay env)."""
    for pattern in _EXCLUDES:
        if not _EXCLUDE_SAFE_RE.match(pattern):
            raise ScanExecutionError(f"Invalid exclude pattern {pattern!r} (unsafe characters)")
    excludes = "".join(f" --exclude {pattern}" for pattern in _EXCLUDES)
    return _JOB_SCRIPT_TEMPLATE.format(
        fetch_cap=_MAX_ARCHIVE_BYTES,
        excludes=excludes,
        jobs=2,  # matches the Job's cpu limit; opengrep's default of 10 just thrashes
        envelope_key=_ENVELOPE_KEY,
        # The shared artifact protocol (ADR 0022) — rendered, never hand-rolled.
        artifact_tail=artifact_emit_tail("$envelope"),
    )


def _validate_archive_url(url: str) -> str:
    """The archive URL comes from the VCS vend seam (trusted-ish) but is still guarded:
    HTTPS only, a plain hostname, no shell-hostile characters (it rides in env and is
    expanded quoted, so this is defense in depth, not the primary control)."""
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ScanExecutionError(f"Archive URL must be https with a host: {cleaned[:120]!r}")
    if re.search(r"[\s'\"\\`;|&<>()]", cleaned):
        raise ScanExecutionError("Archive URL contains unsafe characters")
    return cleaned


class OpengrepScanner(ScannerPort):
    def __init__(self, backend: ScanExecutionBackend):
        self._backend = backend

    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        repo = validate_repo_reference(target.identifier)
        credentials = target.credentials or {}
        token = str(credentials.get("token") or "")
        if not token:
            # No vended envelope = no consent proven (allowlist fail-closed upstream).
            raise ScanExecutionError(f"No VCS read token vended for {repo} — cannot fetch the archive")
        commit_sha = validate_commit_sha(str(credentials.get("commit_sha") or ""))
        archive_url = _validate_archive_url(str(credentials.get("archive_url") or ""))

        rules_yaml = load_ruleset_yaml()
        script = _job_script()
        # Fixed argv, nothing untrusted in the script text: the script is a literal
        # argument and "autosec-opengrep" is $0. URL + rules ride in env; the token
        # rides ONLY in secret_env (a k8s Secret, never argv — argv is visible in ps).
        args = ("/bin/sh", "-c", script, "autosec-opengrep")

        result = self._backend.run(
            ScanJobSpec(
                source=SOURCE,
                image=_OPENGREP_IMAGE,
                # HOME/TMPDIR → the writable emptyDir (read-only rootfs; the
                # single-file engine binary self-extracts to TMPDIR at start).
                env={
                    "OPENGREP_RULES": rules_yaml,
                    "ARCHIVE_URL": archive_url,
                    "HOME": "/tmp",
                    "TMPDIR": "/tmp",
                },
                secret_env={"VCS_TOKEN": token},
                args=args,
                timeout_seconds=_SCAN_TIMEOUT_SECONDS,
                # Raw output travels as an object-storage artifact, not pod-log stdout (ADR
                # 0022). A monorepo's SARIF is the largest document we handle, so this pillar
                # was the most exposed to the pod-log ceiling.
                artifact_path=SCAN_ARTIFACT_PATH,
                workspace_id=str(target.params.get("workspace_id") or ""),
                scan_run_id=str(target.params.get("scan_run_id") or ""),
            ),
            on_progress=on_progress,
        )
        # Fail LOUD, never silent (the Trivy precedent): a non-zero exit means stdout
        # is an error transcript, not scan output. Parsing it would record a COMPLETED
        # run with 0 findings — a crashed scan masquerading as a clean repo.
        if not result.ok:
            snippet = (result.stdout or "").strip().replace("\n", " ")[:300]
            logger.error(
                "opengrep_scan_failed repo=%s commit=%s exit_code=%s timed_out=%s detail=%s",
                repo,
                commit_sha[:12],
                result.exit_code,
                result.timed_out,
                snippet,
            )
            raise ScanExecutionError(
                f"Opengrep scan of {repo}@{commit_sha[:12]} failed "
                f"(exit_code={result.exit_code}, timed_out={result.timed_out})"
            )

        sarif = _unwrap_envelope(result.stdout, repo=repo)
        scan_result = opengrep_sarif_to_scan_result(sarif, repo=repo, commit_sha=commit_sha)
        meta = ScanArtifact(
            kind=_ARTIFACT_KIND_SCAN_META,
            media_type="application/json",
            content=json.dumps(
                {
                    "repo": repo,
                    "commit_sha": commit_sha,
                    "engine_version": scan_result.engine_version,
                }
            ),
        )
        return ScanResult(
            findings=scan_result.findings,
            engine=scan_result.engine,
            engine_version=scan_result.engine_version,
            total_checks=scan_result.total_checks,
            passed_count=scan_result.passed_count,
            failed_count=scan_result.failed_count,
            artifacts=(meta,),
            raw_artifact_ref=result.artifact_ref,  # ADR 0022 D2
        )


def _unwrap_envelope(stdout: str, *, repo: str) -> dict:
    """Extract the SARIF body from the Job's stdout envelope — fail LOUD if unusable.

    This used to warn and return ``{}`` on non-JSON stdout, which the normalizer turned
    into zero findings: a truncated SARIF envelope (a monorepo's SARIF is easily the
    largest output we handle) recorded a COMPLETED run over a mutilated result — a repo
    reported clean because its findings were cut off. ``parse_engine_result_document``
    raises ``IncompleteScanOutputError`` instead (see that module for the full rationale).

    Tolerance kept where it is correct: bare SARIF (LocalSubprocessBackend dev harnesses)
    is still accepted, and a genuinely clean repo's well-formed SARIF with no results
    still completes normally. The content is repo-influenced (D6), so it is parsed as
    untrusted DATA — but "untrusted" means never executed, not silently discarded.
    """
    data = parse_engine_result_document(stdout, engine=_ENGINE_NAME)
    if not isinstance(data, dict):
        raise IncompleteScanOutputError(
            f"Opengrep output for {repo} is a JSON {type(data).__name__}, expected the "
            f"envelope object (or a bare SARIF object)."
        )
    if data.get(_ENVELOPE_KEY) == 1:
        sarif = data.get("sarif")
        if not isinstance(sarif, dict):
            raise IncompleteScanOutputError(
                f"Opengrep envelope for {repo} carries no SARIF object "
                f"(sarif={type(sarif).__name__}) — the engine produced no usable result."
            )
        return sarif
    return data  # tolerate bare SARIF (e.g. LocalSubprocessBackend dev harnesses)
